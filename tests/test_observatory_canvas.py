"""Tests for lib/observatory/canvas_generator.py

Covers:
- generate_canvas(): returns valid JSON string, top-level structure,
  node fields (id, type, x, y, width, height), edge fields
  (id, fromNode, toNode, fromSide, toSide), optional color/label fields,
  node types (file vs text), expected named nodes present,
  all stage files referenced, edge connectivity
"""

from __future__ import annotations

import json

import pytest

from lib.observatory.canvas_generator import generate_canvas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parsed() -> dict:
    return json.loads(generate_canvas())


# ---------------------------------------------------------------------------
# Output is valid JSON
# ---------------------------------------------------------------------------

def test_generate_canvas_returns_string():
    assert isinstance(generate_canvas(), str)


def test_generate_canvas_is_valid_json():
    result = json.loads(generate_canvas())
    assert isinstance(result, dict)


def test_generate_canvas_deterministic():
    assert generate_canvas() == generate_canvas()


# ---------------------------------------------------------------------------
# Top-level structure
# ---------------------------------------------------------------------------

def test_canvas_has_nodes_key():
    assert "nodes" in _parsed()


def test_canvas_has_edges_key():
    assert "edges" in _parsed()


def test_canvas_nodes_is_list():
    assert isinstance(_parsed()["nodes"], list)


def test_canvas_edges_is_list():
    assert isinstance(_parsed()["edges"], list)


def test_canvas_has_nodes():
    assert len(_parsed()["nodes"]) > 0


def test_canvas_has_edges():
    assert len(_parsed()["edges"]) > 0


# ---------------------------------------------------------------------------
# Node fields
# ---------------------------------------------------------------------------

def test_canvas_all_nodes_have_id():
    for node in _parsed()["nodes"]:
        assert "id" in node, f"Node missing id: {node}"


def test_canvas_all_nodes_have_type():
    for node in _parsed()["nodes"]:
        assert "type" in node


def test_canvas_all_nodes_have_coordinates():
    for node in _parsed()["nodes"]:
        assert "x" in node
        assert "y" in node


def test_canvas_all_nodes_have_dimensions():
    for node in _parsed()["nodes"]:
        assert "width" in node
        assert "height" in node


def test_canvas_node_ids_are_unique():
    ids = [n["id"] for n in _parsed()["nodes"]]
    assert len(ids) == len(set(ids))


def test_canvas_node_types_are_valid():
    valid_types = {"file", "text"}
    for node in _parsed()["nodes"]:
        assert node["type"] in valid_types


# ---------------------------------------------------------------------------
# File nodes reference markdown files
# ---------------------------------------------------------------------------

def test_canvas_file_nodes_have_file_field():
    for node in _parsed()["nodes"]:
        if node["type"] == "file":
            assert "file" in node, f"File node missing 'file': {node}"


def test_canvas_file_nodes_reference_md_files():
    for node in _parsed()["nodes"]:
        if node["type"] == "file":
            assert node["file"].endswith(".md"), f"Expected .md: {node['file']}"


# ---------------------------------------------------------------------------
# Text nodes have text field
# ---------------------------------------------------------------------------

def test_canvas_text_nodes_have_text_field():
    for node in _parsed()["nodes"]:
        if node["type"] == "text":
            assert "text" in node


# ---------------------------------------------------------------------------
# Expected named nodes present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("node_id", [
    "capture", "queue", "pipeline", "memory", "metaralph",
    "cognitive", "advisory", "promotion", "chips", "predictions",
    "tuneables", "eidos", "flow",
])
def test_canvas_expected_node_present(node_id):
    ids = {n["id"] for n in _parsed()["nodes"]}
    assert node_id in ids, f"Expected node '{node_id}' not found"


# ---------------------------------------------------------------------------
# All 12 stage files referenced
# ---------------------------------------------------------------------------

def test_canvas_all_12_stage_files_referenced():
    files = {n.get("file", "") for n in _parsed()["nodes"] if n["type"] == "file"}
    for i in range(1, 13):
        prefix = f"{i:02d}-"
        assert any(prefix in f for f in files), f"Stage {i:02d} file not found in canvas"


# ---------------------------------------------------------------------------
# Edge fields
# ---------------------------------------------------------------------------

def test_canvas_all_edges_have_id():
    for edge in _parsed()["edges"]:
        assert "id" in edge


def test_canvas_all_edges_have_from_node():
    for edge in _parsed()["edges"]:
        assert "fromNode" in edge


def test_canvas_all_edges_have_to_node():
    for edge in _parsed()["edges"]:
        assert "toNode" in edge


def test_canvas_all_edges_have_sides():
    for edge in _parsed()["edges"]:
        assert "fromSide" in edge
        assert "toSide" in edge


def test_canvas_edge_ids_are_unique():
    ids = [e["id"] for e in _parsed()["edges"]]
    assert len(ids) == len(set(ids))


def test_canvas_edge_sides_are_valid():
    valid_sides = {"left", "right", "top", "bottom"}
    for edge in _parsed()["edges"]:
        assert edge["fromSide"] in valid_sides
        assert edge["toSide"] in valid_sides


# ---------------------------------------------------------------------------
# Edge connectivity — referenced nodes exist
# ---------------------------------------------------------------------------

def test_canvas_edge_from_nodes_exist():
    node_ids = {n["id"] for n in _parsed()["nodes"]}
    for edge in _parsed()["edges"]:
        assert edge["fromNode"] in node_ids, f"fromNode '{edge['fromNode']}' not in nodes"


def test_canvas_edge_to_nodes_exist():
    node_ids = {n["id"] for n in _parsed()["nodes"]}
    for edge in _parsed()["edges"]:
        assert edge["toNode"] in node_ids, f"toNode '{edge['toNode']}' not in nodes"


# ---------------------------------------------------------------------------
# Optional fields — color and label
# ---------------------------------------------------------------------------

def test_canvas_some_nodes_have_color():
    colors = [n.get("color") for n in _parsed()["nodes"] if "color" in n]
    assert len(colors) > 0


def test_canvas_some_edges_have_label():
    labels = [e.get("label") for e in _parsed()["edges"] if "label" in e]
    assert len(labels) > 0


def test_canvas_color_is_string_when_present():
    for node in _parsed()["nodes"]:
        if "color" in node:
            assert isinstance(node["color"], str)
