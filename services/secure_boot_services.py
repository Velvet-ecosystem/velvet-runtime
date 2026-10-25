# SPDX-License-Identifier: GPL-3.0-only
"""Provision the execution pipeline before loading runtime modules."""

import os

from services.module_loader import ModuleLoader
from services.pipeline_provisioning import provision_runtime_pipeline


class PipelineProvisioningError(RuntimeError):
    pass


class ModuleLoadingError(RuntimeError):
    pass


def provision_pipeline_then_load_modules(
    *,
    identity_context,
    safe_publish,
    provisioner=provision_runtime_pipeline,
    loader_factory=ModuleLoader,
    lifecycle_owner=None,
):
    try:
        pipeline = provisioner(
            capability_context=identity_context.capability_context,
        )
    except Exception as exc:
        raise PipelineProvisioningError(str(exc)) from exc

    try:
        loader = loader_factory(
            modules_dir="modules",
            safe_publish=safe_publish,
        )
        # Keep the existing constructor contract for educational loader fixtures.
        if hasattr(loader, 'required_modules'):
            loader.required_modules = tuple(name.strip() for name in
                os.environ.get('VELVET_REQUIRED_MODULES', '').split(',') if name.strip())
            if any(not name.isidentifier() or name.startswith('_') for name in loader.required_modules):
                raise ValueError('invalid required module name')
        if lifecycle_owner is not None:
            lifecycle_owner.add('modules', loader.stop_all)
        loader.load_all()
        if hasattr(pipeline, '__dict__'):
            pipeline.module_loader = loader
    except Exception as exc:
        if 'loader' in locals() and callable(getattr(loader, 'stop_all', None)):
            try:
                loader.stop_all()
            except Exception as cleanup_exc:
                raise ModuleLoadingError('%s; cleanup failed: %s' % (exc, cleanup_exc)) from exc
        raise ModuleLoadingError(str(exc)) from exc

    return pipeline
