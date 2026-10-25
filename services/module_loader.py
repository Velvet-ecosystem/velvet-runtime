"""Load trusted modules with only safe publish; own their bounded lifecycle.

Required modules fail boot. Optional failures degrade health. A module may expose
stop() for partial-register rollback and shutdown, or return an object with stop().
Python plugins are trusted in-process code, not a security sandbox.
"""
import importlib.util
import inspect
import os
import sys
from velvet_logging.logger import get_logger

logger = get_logger('velvet.module_loader')
_FORBIDDEN_PARAMS = frozenset({'enforcer', 'bus', 'runtime', 'event_bus'})


class RequiredModuleError(RuntimeError):
    pass


class ModuleLoader:
    def __init__(self, modules_dir: str, safe_publish, required_modules=()):
        self.modules_dir = modules_dir
        self._safe_publish = safe_publish
        self.required_modules = tuple(required_modules)
        if any(not isinstance(name, str) or not name.isidentifier() or name.startswith('_')
               for name in self.required_modules):
            raise ValueError('required module names must be public Python identifiers')
        self._loaded = []
        self._resources = []
        self.failures = {}
        self.stop_failures = []
        self._started = False

    @property
    def healthy(self):
        return self._started and not self.failures and not self.stop_failures

    def load_all(self):
        if self._started or self._resources or self.stop_failures:
            raise RuntimeError('loader already started or has unresolved cleanup failure')
        self.failures = {}
        candidates = sorted(f for f in os.listdir(self.modules_dir)
                            if f.endswith('.py') and not f.startswith('_')) if os.path.isdir(self.modules_dir) else []
        missing = set(self.required_modules) - {f[:-3] for f in candidates}
        if missing:
            raise RequiredModuleError('required modules missing: %s' % ', '.join(sorted(missing)))
        try:
            for filename in candidates:
                if not self._load_module(filename) and filename[:-3] in self.required_modules:
                    raise RequiredModuleError('required module failed: %s' % filename[:-3])
            self._started = True
        except BaseException:
            self.stop_all()
            raise

    def _load_module(self, filename):
        name = filename[:-3]
        previous = sys.modules.get(name)
        mod = None
        stop = None
        try:
            spec = importlib.util.spec_from_file_location(name, os.path.join(self.modules_dir, filename))
            if spec is None or spec.loader is None:
                raise ValueError('cannot create import spec')
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            stop = getattr(mod, 'stop', None)
            if stop is not None and not callable(stop):
                raise TypeError('stop must be callable')
            register = getattr(mod, 'register', None)
            if not callable(register):
                raise TypeError('register(publish) required')
            params = inspect.signature(register).parameters
            if 'publish' not in params or _FORBIDDEN_PARAMS.intersection(params):
                raise ValueError('register must accept publish without Runtime internals')
            result = register(publish=self._safe_publish)
            returned_stop = getattr(result, 'stop', None)
            if returned_stop is not None:
                if not callable(returned_stop):
                    raise TypeError('returned stop must be callable')
                stop = returned_stop
            self._resources.append((name, mod, previous, stop))
            self._loaded.append(name)
            return True
        except BaseException as exc:
            # A module-level stop must handle incomplete import/register safely.
            if stop is None and mod is not None:
                stop = getattr(mod, 'stop', None)
            if callable(stop):
                try:
                    stop()
                except BaseException as stop_exc:
                    self.stop_failures.append((name, str(stop_exc)))
            self._restore(name, mod, previous)
            self.failures[name] = str(exc)
            logger.error('[BOOT] Module %s failed: %s', name, exc)
            if not isinstance(exc, Exception):
                raise
            if self.stop_failures:
                raise RequiredModuleError('partial module cleanup failed: %s' % name) from exc
            return False

    @staticmethod
    def _restore(name, mod, previous):
        if sys.modules.get(name) is mod:
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    def stop_all(self):
        while self._resources:
            name, mod, previous, stop = self._resources.pop()
            try:
                if stop is not None:
                    stop()
            except BaseException as exc:
                self.stop_failures.append((name, str(exc)))
                logger.error('[SHUTDOWN] Module %s failed to stop: %s', name, exc)
            finally:
                self._restore(name, mod, previous)
        self._loaded = []
        self._started = False
        if self.stop_failures:
            raise RuntimeError('module cleanup failed: %s' % self.stop_failures)
