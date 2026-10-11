"""Environment Generator: deterministic, engine-agnostic procedural environments.

The generator turns a :class:`~environment_generator.models.LocationBlueprint`
(a structured description of a real-world location), a
:class:`~environment_generator.models.LocationRecipe` (how to stylise it) and
optional :class:`~environment_generator.models.LocationOverrides` into a
portable scene manifest.

Entry points:

* :class:`environment_generator.pipeline.Pipeline` for library use.
* The ``envgen`` command line interface (:mod:`environment_generator.cli`).
"""

__version__ = "0.2.0"

#: Name recorded in manifests and reports.
GENERATOR_NAME = "environment-generator"

__all__ = ["GENERATOR_NAME", "__version__"]
