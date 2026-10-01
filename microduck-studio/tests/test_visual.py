import copy

import pytest

from microduck_studio.core import StudioStore, validate_assembly
from microduck_studio.visual import VisualStore, RevisionConflict, model_manifest, model_reference, validate_visual


def config():
    model = model_manifest()
    return {"palette": {"schemaVersion": 1, "modelId": model["modelId"], "name": "我的奶油鸭",
            "lighting": {"preset": "studio", "intensity": 1, "azimuth": -35}, "surface": {"layers": True},
            "parts": {p["id"]: {"color": p["defaultColor"], "material": p["defaultMaterial"]} for p in model["parts"]}},
            "inventory": {"schemaVersion": 1, "items": [{"id": "pla-white", "name": "白色", "color": "#ffffff", "material": "pla"}]}}


def test_versions_survive_restart_are_project_scoped_and_cannot_overwrite(tmp_path):
    path = tmp_path / "studio.db"
    studio = StudioStore(path)
    a = studio.create_project("A", str(tmp_path))["id"]
    b = studio.create_project("B", str(tmp_path))["id"]
    store = VisualStore(path)
    one = store.save(a, config(), 0)
    changed = config()
    changed["palette"]["name"] = "第二版"
    two = store.save(a, changed, 1)
    with pytest.raises(RevisionConflict):
        store.save(a, config(), 1)
    with pytest.raises(KeyError):
        store.save("unknown", config(), 0)
    assert VisualStore(path).list(a) == [two, one]
    assert store.list(b) == []
    assert one["data"]["inventory"]["items"][0]["color"] == "#FFFFFF"
    assert studio.get_project(a)["status"] == "needs_confirmation"


@pytest.mark.parametrize("mutation", [
    lambda d: d["palette"].update(modelId="other"),
    lambda d: d["palette"]["parts"].pop(next(iter(d["palette"]["parts"]))),
    lambda d: d["palette"]["parts"].update(foreign={"color": "#000000", "material": "pla"}),
    lambda d: d["palette"]["lighting"].update(intensity=float("nan")),
    lambda d: d["palette"]["surface"].update(layers=0),
    lambda d: d["palette"]["lighting"].update(preset=[]),
    lambda d: d["inventory"]["items"][0].update(material={}),
    lambda d: next(iter(d["palette"]["parts"].values())).update(material=[]),
    lambda d: d["inventory"]["items"].append(copy.deepcopy(d["inventory"]["items"][0])),
    lambda d: d["inventory"]["items"][0].update(color="red"),
    lambda d: next(iter(d["palette"]["parts"].values())).update(coating={"kind": "acrylic", "color": "#000000"}),
])
def test_invalid_visual_data_is_atomic(tmp_path, mutation):
    path = tmp_path / "studio.db"
    studio = StudioStore(path)
    project = studio.create_project("A", str(tmp_path))["id"]
    store = VisualStore(path)
    original = store.save(project, config(), 0)
    value = config()
    mutation(value)
    with pytest.raises(ValueError):
        store.save(project, value, 1)
    assert store.list(project) == [original]


def test_reference_geometry_links_preserved_without_implying_assembly_pass():
    part = model_manifest()["parts"][0]["id"]
    data = {"title": "结构试装", "model_binding": model_reference(), "checks": [
        {"id": "fit", "title": "核对间隙", "status": "pending", "evidence": [], "part_ids": [part]}]}
    normalized, status = validate_assembly(data)
    assert status == "incomplete"
    assert normalized["checks"][0]["part_ids"] == [part]
    assert normalized["model_binding"]["scope"] == "reference_geometry_only"
    for bad in ["foreign", part + "x"]:
        data["checks"][0]["part_ids"] = [bad]
        with pytest.raises(ValueError):
            validate_assembly(data)
    data["checks"][0]["part_ids"] = [part]
    del data["model_binding"]
    with pytest.raises(ValueError):
        validate_assembly(data)


def test_linked_check_still_requires_evidence():
    with pytest.raises(ValueError, match="requires evidence"):
        validate_assembly({"title": "检查", "model_binding": model_reference(), "checks": [
            {"id": "fit", "title": "间隙", "status": "passed", "part_ids": [model_manifest()["parts"][0]["id"]]}]})
