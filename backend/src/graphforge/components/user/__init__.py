"""Drop-in folder for project-specific components.

One file per component: subclass BaseComponent/RouterComponent/
ToolProviderComponent, decorate with @register, define a pydantic config,
declare state_reads/state_writes. No frontend changes needed (CLAUDE.md §18).
"""
