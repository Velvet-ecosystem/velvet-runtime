# Founder chmod compatibility

The current-frame publisher sets the temporary frame file mode with `os.fchmod()` before the atomic replace. That descriptor-level mode is preserved by `os.replace()`.

Some Founder-class Python/Linux builds expose `os.chmod(..., follow_symlinks=False)` but raise `NotImplementedError` when it is called. The post-replace chmod is therefore redundant and should not be required for correctness or safety.

The target path is rejected if it is a symlink before publication, and the replacement file is created locally in the already-validated parent directory.
