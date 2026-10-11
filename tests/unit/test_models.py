from __future__ import annotations

import pytest
from pydantic import ValidationError

from environment_generator.core.errors import ContractValidationError
from environment_generator.models.geometry import (
    PolygonGeometry,
    PolylineGeometry,
    RectangleGeometry,
    area_outline,
    geometry_points,
)
from environment_generator.models.overrides import (
    AddEntity,
    DeleteEntity,
    LocationOverrides,
    ReplaceArchetype,
    UpdateEntity,
)
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.scene import TerrainData
from environment_generator.models.site import (
    SiteDescription,
    VegetationArea,
    VegetationPoint,
)
from environment_generator.validation.contract import parse_document
from tests.conftest import make_recipe, make_site, road, site_data


def test_site_vegetation_kind_selects_geometry_type() -> None:
    ok = make_site(
        vegetation=[{"id": "t", "kind": "tree", "geometry": {"type": "point", "position": [1, 1]}}]
    )
    assert isinstance(ok.vegetation[0], VegetationPoint)
    area = make_site(
        vegetation=[
            {
                "id": "f",
                "kind": "forest",
                "geometry": {"type": "polygon", "points": [[0, 0], [9, 0], [9, 9]]},
            }
        ]
    )
    assert isinstance(area.vegetation[0], VegetationArea)
    with pytest.raises(ValidationError):
        make_site(
            vegetation=[
                {"id": "f", "kind": "forest", "geometry": {"type": "point", "position": [1, 1]}}
            ]
        )


def test_site_rejects_unknown_fields_and_dotted_ids() -> None:
    with pytest.raises(ValidationError, match="extra"):
        SiteDescription.model_validate(site_data(colour="red"))
    with pytest.raises(ValidationError, match="pattern"):
        make_site(roads=[road("r.1", [[0, 0], [10, 0]])])


def test_polygon_points_are_normalised() -> None:
    polygon = PolygonGeometry(type="polygon", points=[(0, 0), (1, 0), (1, 1), (1, 1), (0, 0)])
    assert polygon.points == [(0, 0), (1, 0), (1, 1)]
    with pytest.raises(ValidationError):
        PolygonGeometry(type="polygon", points=[(0, 0), (1, 1), (0, 0)])
    with pytest.raises(ValidationError):
        PolylineGeometry(type="polyline", points=[(1, 1), (1, 1)])


def test_area_outline_of_rectangle() -> None:
    rectangle = RectangleGeometry(type="rectangle", center=(5, 5), size=(4, 2))
    assert sorted(area_outline(rectangle)) == [(3.0, 4.0), (3.0, 6.0), (7.0, 4.0), (7.0, 6.0)]
    assert len(geometry_points(rectangle)) == 4


def test_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_site(extent={"width_m": float("inf"), "depth_m": 10})


def test_recipe_defaults_and_generator_flags() -> None:
    recipe = LocationRecipe.default()
    assert recipe.seed is None  # falls back to the blueprint's masterSeed
    assert recipe.structural_similarity is None
    assert all(recipe.generator_enabled(name) for name in GeneratorName)
    disabled = make_recipe(props={"enabled": False})
    assert not disabled.generator_enabled(GeneratorName.PROPS)


def test_weathering_implies_preferred_tag() -> None:
    recipe = make_recipe(style={"weathering": 0.7})
    assert "weathered" in recipe.effective_preferred_tags()
    assert "weathered" not in LocationRecipe.default().effective_preferred_tags()


def test_public_documents_accept_camel_case_only() -> None:
    data = {"schemaVersion": "1.0", "id": "r", "name": "R", "detailDensity": 2.0}
    assert parse_document(LocationRecipe, data, "recipe").detail_density == 2.0
    with pytest.raises(ContractValidationError) as info:
        parse_document(LocationRecipe, {**data, "detail_density": 2.0}, "recipe")
    assert any(issue.path == "detail_density" for issue in info.value.issues)


def test_recipe_rejects_unknown_building_and_prop_kinds() -> None:
    with pytest.raises(ValidationError):
        make_recipe(buildings={"zoneFill": {"buildingWeights": {"castle": 1}}})
    with pytest.raises(ValidationError):
        make_recipe(props={"clutter": {"kindWeights": {"wreck": 1}}})


def test_overrides_discriminated_operations() -> None:
    overrides = LocationOverrides.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "o",
            "locationId": "loc",
            "entityOperations": [
                {"op": "update", "id": "b-1", "patch": {"floors": 2}},
                {"op": "replaceArchetype", "id": "b-2", "archetype": "wooden_house_small"},
                {"op": "delete", "id": "t-1", "expectedType": "trees"},
                {"op": "add", "collection": "props", "entity": {"id": "p-1"}},
            ],
            "placementOverrides": [{"entityId": "prop.p-1", "yawDeg": 90}],
        }
    )
    kinds = [type(op) for op in overrides.entity_operations]
    assert kinds == [UpdateEntity, ReplaceArchetype, DeleteEntity, AddEntity]
    assert overrides.conflict_policy.value == "fail"
    with pytest.raises(ValidationError):
        LocationOverrides.model_validate(
            {
                "schemaVersion": "1.0",
                "id": "o",
                "locationId": "loc",
                "entityOperations": [{"op": "explode", "id": "x"}],
            }
        )


def test_terrain_data_shape_is_checked() -> None:
    with pytest.raises(ValidationError, match="rows"):
        TerrainData(
            cell_size_m=1.0,
            columns=2,
            rows=2,
            heights=[[0.0, 0.0]],
            min_elevation_m=0.0,
            max_elevation_m=0.0,
            ground_cover="grass",
        )
