# SPDX-License-Identifier: GPL-3.0-only
"""Provision the execution pipeline before loading runtime modules."""

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
        loader.load_all()
    except Exception as exc:
        raise ModuleLoadingError(str(exc)) from exc

    return pipeline
