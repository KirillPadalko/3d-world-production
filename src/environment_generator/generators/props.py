"""Explicit props and clutter scattered around buildings."""

from __future__ import annotations

from environment_generator.assets.resolver import AssetRequest
from environment_generator.core.geometry import add, rectangle_corners, rotate
from environment_generator.core.spatial import Footprint
from environment_generator.generators.base import (
    GenerationContext,
    GeneratorOutput,
    PropGenerator,
    WorkEstimate,
    feature_ref,
    kinds_with_hint,
    make_entity,
)
from environment_generator.models.assets import AssetCategory, AssetNeed
from environment_generator.models.recipe import LocationRecipe
from environment_generator.models.scene import SceneEntity
from environment_generator.models.site import BuildingKind, PropKind, SiteDescription

#: Default clutter mix per building kind (relative weights).
CLUTTER_TABLE: dict[str, dict[PropKind, float]] = {
    BuildingKind.HOUSE: {
        PropKind.WOODPILE: 2,
        PropKind.BENCH: 1,
        PropKind.BARREL: 1,
        PropKind.WHEELBARROW: 0.5,
        PropKind.BICYCLE: 0.5,
    },
    BuildingKind.BATHHOUSE: {PropKind.WOODPILE: 3, PropKind.BUCKET: 1, PropKind.BENCH: 1},
    BuildingKind.GREENHOUSE: {PropKind.BUCKET: 2, PropKind.TOOLS: 1, PropKind.WHEELBARROW: 1},
    BuildingKind.OUTHOUSE: {PropKind.BUCKET: 1},
    BuildingKind.GAZEBO: {PropKind.BENCH: 2},
    BuildingKind.WORKSHOP: {PropKind.TOOLS: 2, PropKind.TIRES: 1, PropKind.BARREL: 1},
    BuildingKind.APARTMENT_BLOCK: {PropKind.DUMPSTER: 2, PropKind.BENCH: 2, PropKind.CAR: 1.5},
    BuildingKind.BARN: {PropKind.HAY_BALE: 3, PropKind.CART: 1, PropKind.BARREL: 1},
    BuildingKind.SHED: {
        PropKind.CRATE: 1,
        PropKind.BARREL: 1,
        PropKind.WOODPILE: 1,
        PropKind.TOOLS: 1,
    },
    BuildingKind.GARAGE: {PropKind.TIRES: 2, PropKind.BARREL: 2, PropKind.CAR: 1},
    BuildingKind.WAREHOUSE: {
        PropKind.CRATE: 3,
        PropKind.PALLET: 2,
        PropKind.BARREL: 2,
        PropKind.DUMPSTER: 1,
    },
    BuildingKind.FACTORY: {
        PropKind.BARREL: 3,
        PropKind.PALLET: 2,
        PropKind.CRATE: 2,
        PropKind.TIRES: 1,
        PropKind.DUMPSTER: 1,
    },
    BuildingKind.SHOP: {PropKind.CRATE: 2, PropKind.BENCH: 1, PropKind.DUMPSTER: 1},
    BuildingKind.OFFICE: {PropKind.BENCH: 1, PropKind.DUMPSTER: 1, PropKind.CAR: 1},
    BuildingKind.CHURCH: {PropKind.BENCH: 2},
}
DEFAULT_CLUTTER: dict[PropKind, float] = {PropKind.CRATE: 1, PropKind.BARREL: 1}

PROP_BLOCKERS = frozenset(category.value for category in AssetCategory) - {
    AssetCategory.TERRAIN.value
}
PLACEMENT_ATTEMPTS = 6


class ClutterPropGenerator(PropGenerator):
    implementation = "clutter_props"
    version = "1.1.0"

    def estimate(self, site: SiteDescription, recipe: LocationRecipe) -> WorkEstimate:
        sources = [feature_ref("props", p.id) for p in site.props]
        needs = [
            AssetNeed(
                category=AssetCategory.PROP,
                kinds=list(kinds_with_hint(p.archetype, p.kind.value)),
                reason=feature_ref("props", p.id),
            )
            for p in site.props
        ]
        count = len(site.props)
        clutter = recipe.props.clutter
        if clutter.enabled and clutter.per_building > 0:
            count += int(len(site.buildings) * clutter.per_building)
            kinds: set[PropKind] = set()
            if clutter.kind_weights:
                kinds.update(clutter.kind_weights)
            else:
                for building in site.buildings:
                    kinds.update(CLUTTER_TABLE.get(building.kind, DEFAULT_CLUTTER))
            needs.extend(
                AssetNeed(
                    category=AssetCategory.PROP, kinds=[k.value], reason="recipe.props.clutter"
                )
                for k in sorted(kinds)
            )
        return WorkEstimate(tuple(sources), count, tuple(needs))

    def generate(self, context: GenerationContext) -> GeneratorOutput:
        output = GeneratorOutput()
        for prop in sorted(context.site.props, key=lambda p: p.id):
            entity_id = f"prop.{prop.id}"
            x, y = prop.geometry.position
            selection = context.assets.resolve(
                AssetRequest(
                    AssetCategory.PROP,
                    kinds_with_hint(prop.archetype, prop.kind.value),
                    entity_id=entity_id,
                )
            )
            entity = make_entity(
                self,
                entity_id=entity_id,
                category=AssetCategory.PROP,
                kind=prop.kind.value,
                selection=selection,
                position=(x, y, context.terrain.height_at(x, y)),
                yaw_deg=prop.geometry.rotation_deg,
                rule="explicit_point",
                source_feature=feature_ref("props", prop.id),
                attributes=prop.attributes,
                tags=prop.tags,
            )
            output.entities.append(entity)
            context.occupy(entity)
        clutter = context.recipe.props.clutter
        if clutter.enabled and clutter.per_building > 0:
            for building in sorted(context.entities_of(AssetCategory.BUILDING), key=lambda b: b.id):
                self._clutter(context, building, output)
        return output

    def _clutter(
        self, context: GenerationContext, building: SceneEntity, output: GeneratorOutput
    ) -> None:
        config = context.recipe.props.clutter
        table = config.kind_weights or CLUTTER_TABLE.get(building.kind, DEFAULT_CLUTTER)
        kinds = sorted(table)
        weights = [table[k] for k in kinds]
        expected = config.per_building * context.controls.detail_density
        whole = int(expected)
        count = whole + (1 if context.unit("clutter", building.id) < expected - whole else 0)
        suffix = building.id.removeprefix("building.")
        center = (building.transform.position[0], building.transform.position[1])
        half_w, half_d = building.dimensions.width_m / 2.0, building.dimensions.depth_m / 2.0
        extent = context.site.extent
        for index in range(count):
            prop_id = f"prop.clutter.{suffix}.{index:02d}"
            rng = context.rng("clutter", building.id, index)
            kind = kinds[rng.weighted_index(weights)]
            selection = context.assets.resolve(
                AssetRequest(AssetCategory.PROP, (kind.value,), entity_id=prop_id)
            )
            dims = selection.archetype.dimensions
            for _ in range(PLACEMENT_ATTEMPTS):
                side = rng.randint(0, 3)
                along = rng.uniform(-0.45, 0.45)
                gap = rng.uniform(0.6, config.max_distance_m)
                reach = max(dims.width_m, dims.depth_m) / 2.0
                local = (
                    (along * 2 * half_w, half_d + gap + reach),
                    (along * 2 * half_w, -(half_d + gap + reach)),
                    (half_w + gap + reach, along * 2 * half_d),
                    (-(half_w + gap + reach), along * 2 * half_d),
                )[side]
                point = add(center, rotate(local, building.transform.yaw_deg))
                yaw = (
                    building.transform.yaw_deg + 90.0 * rng.randint(0, 3) + rng.uniform(-12.0, 12.0)
                )
                corners = rectangle_corners(point, dims.width_m, dims.depth_m, yaw)
                if not all(
                    0.0 <= x <= extent.width_m and 0.0 <= y <= extent.depth_m for x, y in corners
                ):
                    continue
                probe = Footprint.from_polygon(prop_id, "probe", corners).inflated(0.3)
                if context.occupancy.collides(probe, layers=PROP_BLOCKERS):
                    continue
                entity = make_entity(
                    self,
                    entity_id=prop_id,
                    category=AssetCategory.PROP,
                    kind=kind.value,
                    selection=selection,
                    position=(point[0], point[1], context.terrain.height_at(*point)),
                    yaw_deg=yaw,
                    rule="building_clutter",
                    source_feature=building.provenance.source_feature,
                    parameters={"near_entity": building.id},
                )
                output.entities.append(entity)
                context.occupy(entity)
                break
