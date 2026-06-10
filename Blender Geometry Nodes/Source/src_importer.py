"""Import KUKA .src robot programs and convert to PRC geometry."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional

import bpy
import mathutils


@dataclass
class Motion:
    """Parsed motion command."""
    motion_type: int  # 0=AXIS, 1=PTP, 2=LIN, 3=Action
    speed: float = 10.0
    axes: list[float] = field(default_factory=lambda: [0.0] * 6)
    position: mathutils.Vector = field(default_factory=lambda: mathutils.Vector((0.0, 0.0, 0.0)))
    orient: mathutils.Quaternion = field(default_factory=mathutils.Quaternion)
    posture: str = "010"
    tool_id: str = "0"


class KukaParser:
    """Parse KUKA KRL .src file to extract motion commands."""

    def __init__(self, text: str):
        self.text = text
        self.motions: list[Motion] = []

    def parse(self) -> list[Motion]:
        """Extract motion commands from KRL source."""
        # Normalize line endings, then scan every command block.
        text = self.text.replace('\r\n', '\n').replace('\r', '\n')

        cmd_pattern = re.compile(r'\b(PTP|LIN)\s*\{([^}]*)\}', re.IGNORECASE | re.DOTALL)
        for match in cmd_pattern.finditer(text):
            command_type = match.group(1).upper()
            block = match.group(2)

            speed = self._extract_speed(block, 10.0 if command_type == 'PTP' else 100.0)
            axes = self._extract_axes_from_block(block)
            cart = self._extract_cartesian_from_block(block)

            # Prefer explicit axis targets for PTP. For LIN, only cartesian is valid.
            if command_type == 'PTP' and axes is not None:
                self.motions.append(
                    Motion(
                        motion_type=0,
                        speed=speed,
                        axes=axes,
                        position=mathutils.Vector((0.0, 0.0, 0.0)),
                        orient=mathutils.Quaternion((1.0, 0.0, 0.0, 0.0)),
                    )
                )
                continue

            if cart is None:
                continue

            position, orient = cart
            self.motions.append(
                Motion(
                    motion_type=1 if command_type == 'PTP' else 2,
                    speed=speed,
                    axes=[0.0] * 6,
                    position=position,
                    orient=orient,
                )
            )

        return self.motions

    def _extract_axes_from_block(self, block: str) -> Optional[list[float]]:
        """Extract A1..A6 values from a PTP/LIN block. Returns None if not all found."""
        axes = [None] * 6
        for i in range(1, 7):
            value = self._extract_float(block, f"A{i}")
            if value is not None:
                axes[i - 1] = value
        # Only return if we found all 6 axes.
        if all(a is not None for a in axes):
            return [float(a) for a in axes]
        return None

    def _extract_cartesian_from_block(
        self,
        block: str,
    ) -> Optional[tuple[mathutils.Vector, mathutils.Quaternion]]:
        """Extract XYZABC cartesian target from a command block."""
        x = self._extract_float(block, "X")
        y = self._extract_float(block, "Y")
        z = self._extract_float(block, "Z")

        if x is None or y is None or z is None:
            return None

        # KUKA A/B/C convention is Z/Y/X rotations in degrees.
        a = self._extract_float(block, "A") or 0.0
        b = self._extract_float(block, "B") or 0.0
        c = self._extract_float(block, "C") or 0.0
        euler = mathutils.Euler((math.radians(c), math.radians(b), math.radians(a)), "ZYX")
        orient = euler.to_quaternion()

        position = mathutils.Vector((x, y, z))
        return position, orient

    def _extract_float(self, text: str, key: str) -> Optional[float]:
        """Extract a float value from either KEY value or KEY=value syntax."""
        pattern = rf'\b{re.escape(key)}\b\s*(?:=)?\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)'
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            return None
        try:
            return float(match.group(1))
        except ValueError:
            return None

    def _extract_speed(self, line: str, default: float) -> float:
        """Extract speed value from command block."""
        speed_match = re.search(r'\bSPeed\b\s*(?:=)?\s*([0-9.]+)', line, re.IGNORECASE)
        if speed_match:
            try:
                return float(speed_match.group(1))
            except ValueError:
                pass
        return default


def create_geometry_from_motions(motions: list[Motion]) -> Optional[bpy.types.Mesh]:
    """Create Blender geometry with PRC attributes from parsed motions."""
    if not motions:
        return None

    mesh = bpy.data.meshes.new("SRC_Import")
    
    # Use cartesian targets directly; for axis-only points keep the last
    # known cartesian position so the path remains contiguous.
    verts: list[tuple[float, float, float]] = []
    last_pos = mathutils.Vector((0.0, 0.0, 0.0))
    for m in motions:
        if m.motion_type in {1, 2}:
            last_pos = m.position.copy()
        verts.append((float(last_pos.x), float(last_pos.y), float(last_pos.z)))

    mesh.vertices.add(len(verts))
    for i, v in enumerate(verts):
        mesh.vertices[i].co = v

    # Create edges connecting consecutive vertices
    edges = [(i, i + 1) for i in range(len(verts) - 1)]
    mesh.edges.add(len(edges))
    for i, (a, b) in enumerate(edges):
        mesh.edges[i].vertices = (a, b)

    # Add attributes
    _add_attribute(mesh, "prc_motion", "INT", [m.motion_type for m in motions])
    _add_attribute(mesh, "prc_speed", "FLOAT", [m.speed for m in motions])
    _add_attribute(mesh, "prc_group_type", "INT", [1 if m.motion_type in {0, 1} else 0 for m in motions])
    _add_attribute(mesh, "prc_posture", "INT", [10 for _ in motions])
    _add_attribute(mesh, "prc_a1", "FLOAT", [m.axes[0] for m in motions])
    _add_attribute(mesh, "prc_a2", "FLOAT", [m.axes[1] for m in motions])
    _add_attribute(mesh, "prc_a3", "FLOAT", [m.axes[2] for m in motions])
    _add_attribute(mesh, "prc_a4", "FLOAT", [m.axes[3] for m in motions])
    _add_attribute(mesh, "prc_a5", "FLOAT", [m.axes[4] for m in motions])
    _add_attribute(mesh, "prc_a6", "FLOAT", [m.axes[5] for m in motions])
    
    # Cartesian attributes (position and orientation)
    _add_vector_attribute(mesh, "prc_position", [m.position for m in motions])
    _add_quat_attribute(mesh, "prc_orient", [m.orient for m in motions])
    
    _add_attribute(mesh, "prc_tool_id", "INT", [int(m.tool_id) for m in motions])

    return mesh


def _add_attribute(mesh: bpy.types.Mesh, name: str, attr_type: str, values: list) -> None:
    """Add a scalar attribute to the mesh."""
    attr = mesh.attributes.new(name, attr_type, "POINT")
    for i, val in enumerate(values):
        attr.data[i].value = val


def _add_vector_attribute(mesh: bpy.types.Mesh, name: str, vectors: list) -> None:
    """Add a vector attribute (position) to the mesh."""
    attr = mesh.attributes.new(name, "FLOAT_VECTOR", "POINT")
    for i, v in enumerate(vectors):
        attr.data[i].vector = (float(v.x), float(v.y), float(v.z))


def _add_quat_attribute(mesh: bpy.types.Mesh, name: str, quats: list) -> None:
    """Add a quaternion attribute (orientation) to the mesh."""
    attr = mesh.attributes.new(name, "QUATERNION", "POINT")
    for i, q in enumerate(quats):
        attr.data[i].value = (float(q.w), float(q.x), float(q.y), float(q.z))


def import_src_file(filepath: str, scene: bpy.types.Scene) -> tuple[bool, str]:
    """Import a .src file and populate the PRC_Program carrier object."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return False, f"Failed to read file: {e!r}"

    parser = KukaParser(content)
    motions = parser.parse()

    if not motions:
        return False, "No motion commands found in .src file."

    mesh = create_geometry_from_motions(motions)
    if mesh is None:
        return False, "Failed to create geometry."

    # Find or create the PRC_Program carrier object
    carrier = bpy.data.objects.get("PRC_Program")
    if carrier is None:
        return False, "PRC_Program carrier not found. Run 'Generate Geometry Node Groups' first."

    # Remove all Geometry Nodes modifiers to stop overriding our mesh
    for mod in list(carrier.modifiers):
        if mod.type == "NODES":
            carrier.modifiers.remove(mod)

    # Clear existing mesh data
    if carrier.data and isinstance(carrier.data, bpy.types.Mesh):
        old_mesh = carrier.data
        carrier.data = mesh
        bpy.data.meshes.remove(old_mesh)
    else:
        carrier.data = mesh

    return True, f"Imported {len(motions)} motion commands."
