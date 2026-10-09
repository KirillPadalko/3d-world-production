from __future__ import annotations

import pytest
from pydantic import ValidationError

from environment_generator.models.blueprint import (
    FeatureCollection,
    LocationBlueprint,
    VegetationArea,
    VegetationLine,
    VegetationPoint,
)
from environment_generator.models.geometry import (
    PolygonGeometry,
    PolylineGeometry,
    RectangleGeometry,
    area_outline,
    geometry_points,
)
from environment_generator.models.overrides import LocationOverrides, PatchFeature, SetTransform
from environment_generator.models.recipe import GeneratorName, LocationRecipe
from environment_generator.models.scene import TerrainData
from tests.conftest import RURAL_BLUEPRINT, blueprint_data, load_json, make_blueprint, road


def test_example_blueprint_parses() -> None:
    blueprint = LocationBlueprint.model_validate(load_json(RURAL_BLUEPRINT))
    assert blueprint.id == "rural-crossroads"
    assert blueprint.feature_count() == 47
    kinds = {type(v) for v in blueprint.vegetation}
    assert kinds == {VegetationArea, VegetationLine, VegetationPoint}
    assert len(blueprint.collection(FeatureCollection.BUILDINGS)) == 11


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="extra"):
        LocationBlueprint.model_validate(blueprint_data(colour="red"))


def test_schema_version_is_required_and_pinned() -> None:
    data = blueprint_data()
    del data["schema_version"]
    with pytest.raises(ValidationError):
        LocationBlueprint.model_validate(data)
    with pytest.raises(ValidationError):
        LocationBlueprint.model_validate(blueprint_data(schema_version="2.0"))


def test_identifiers_cannot_contain_dots() -> None:
    with pytest.raises(ValidationError, match="pattern"):
        make_blueprint(roads=[road("r.1", [[0, 0], [10, 0]])])


def test_vegetation_kind_selects_geometry_type() -> None:
    ok = make_blueprint(
        vegetation=[{"id": "t", "kind": "tree", "geometry": {"type": "point", "position": [1, 1]}}]
    )
    assert isinstance(ok.vegetation[0], VegetationPoint)
    with pytest.raises(ValidationError):
        make_blueprint(
            vegetation=[
                {"id": "f", "kind": "forest", "geometry": {"type": "point", "position": [1, 1]}}
            ]
        )


def test_polygon_points_are_normalised() -> None:
    polygon = PolygonGeometry(type="polygon", points=[(0, 0), (1, 0), (1, 1), (1, 1), (0, 0)])
    assert polygon.points == [(0, 0), (1, 0), (1, 1)]
    with pytest.raises(ValidationError):
        PolygonGeometry(type="polygon", points=[(0, 0), (1, 1), (0, 0)])
    with pytest.raises(ValidationError):
        PolylineGeometry(type="polyline", points=[(1, 1), (1, 1)])


def test_area_outline_of_rectangle() -> None:
    rect = RectangleGeometry(type="rectangle", center=(5, 5), size=(4, 2))
    assert sorted(area_outline(rect)) == [(3.0, 4.0), (3.0, 6.0), (7.0, 4.0), (7.0, 6.0)]
    assert len(geometry_points(rect)) == 4


def test_non_finite_numbers_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_blueprint(extent={"width_m": float("inf"), "depth_m": 10})


def test_recipe_defaults_and_generator_flags() -> None:
    recipe = LocationRecipe.default()
    assert recipe.seed == 0
    assert all(recipe.generator_enabled(name) for name in GeneratorName)
    disabled = LocationRecipe.model_validate(
        {"schema_version": "1.0", "id": "r", "name": "R", "props": {"enabled": False}}
    )
    assert not disabled.generator_enabled(GeneratorName.PROPS)


def test_weathering_implies_preferred_tag() -> None:
    recipe = LocationRecipe.model_validate(
        {"schema_version": "1.0", "id": "r", "name": "R", "style": {"weathering": 0.7}}
    )
    assert "weathered" in recipe.effective_preferred_tags()
    assert "weathered" not in LocationRecipe.default().effective_preferred_tags()


def test_overrides_discriminated_operations() -> None:
    overrides = LocationOverrides.model_validate(
        {
            "schema_version": "1.0",
            "id": "o",
            "blueprint_id": "b",
            "feature_operations": [
                {"op": "patch", "collection": "buildings", "id": "b-1", "patch": {"floors": 2}}
            ],
            "entity_operations": [{"op": "set_transform", "entity_id": "prop.p-1", "yaw_deg": 90}],
        }
    )
    assert isinstance(overrides.feature_operations[0], PatchFeature)
    assert isinstance(overrides.entity_operations[0], SetTransform)
    with pytest.raises(ValidationError):
        LocationOverrides.model_validate(
            {
                "schema_version": "1.0",
                "id": "o",
                "blueprint_id": "b",
                "feature_operations": [{"op": "explode", "collection": "buildings", "id": "x"}],
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
