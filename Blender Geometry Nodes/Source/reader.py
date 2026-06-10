"""Read evaluated GN geometry from the PRC_Program carrier and build a proto Task."""

from __future__ import annotations

import bpy
import mathutils

from . import prc_pb2
from . import node_groups as _ng


# ---------------------------------------------------------------------------
# Attribute reading
# ---------------------------------------------------------------------------

class _Point:
    __slots__ = (
        "motion", "speed", "axes", "position", "orient",
        "posture", "tool_id", "group_type",
        "motion_group", "inline_code", "is_comment",
        "action_kind",
    )

    def __init__(self):
        self.motion: int = 0
        self.speed: float = 0.0
        self.axes: list[float] = [0.0] * 6
        self.position: mathutils.Vector = mathutils.Vector((0.0, 0.0, 0.0))
        self.orient: mathutils.Quaternion = mathutils.Quaternion()
        self.posture: str = "010"
        self.tool_id: str = ""
        self.group_type: int = 1
        # Motion-group ID stamped by the Motion Group / Action Group / Curve
        # Helper wrappers. Two adjacent points whose IDs differ start a new
        # motion group at the boundary; identical IDs stay in the same group.
        # 0 means "no ID stamped" — bare motion-command nodes that skipped
        # the wrapper land in their own catch-all group.
        self.motion_group: int = 0
        self.inline_code: str = ""
        self.is_comment: bool = False
        self.action_kind: int = 0


def _read_attr(geo, name, default):
    attr = geo.attributes.get(name)
    if attr is None:
        return None
    return attr


def _attr_int(attr, i, default=0) -> int:
    if attr is None:
        return default
    try:
        return int(attr.data[i].value)
    except Exception:  # noqa: BLE001
        return default


def _attr_float(attr, i, default=0.0) -> float:
    if attr is None:
        return default
    try:
        return float(attr.data[i].value)
    except Exception:  # noqa: BLE001
        return default


def _attr_string(attr, i, default="") -> str:
    if attr is None:
        return default
    try:
        v = attr.data[i].value
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        return str(v)
    except Exception:  # noqa: BLE001
        return default


def _attr_quat(attr, i, default=None) -> mathutils.Quaternion:
    if attr is None:
        return default if default is not None else mathutils.Quaternion()
    try:
        v = attr.data[i].value
        return mathutils.Quaternion((float(v[0]), float(v[1]), float(v[2]), float(v[3])))
    except Exception:  # noqa: BLE001
        return default if default is not None else mathutils.Quaternion()


def _attr_bool(attr, i, default=False) -> bool:
    if attr is None:
        return default
    try:
        return bool(attr.data[i].value)
    except Exception:  # noqa: BLE001
        return default


def _function_subprogram_attr(geo):
    """Return the attribute used to tag function-definition subprogram IDs.

    New node groups write ``prc_function_subprogram_id``; older/legacy trees
    may still use ``prc_function_id``.
    """
    return (
        _read_attr(geo, "prc_function_subprogram_id", None)
        or _read_attr(geo, "prc_function_id", None)
    )


def _read_point(geo, i: int) -> _Point:
    p = _Point()

    motion_attr = _read_attr(geo, "prc_motion", 0)
    p.motion = _attr_int(motion_attr, i, 0)
    p.speed = _attr_float(_read_attr(geo, "prc_speed", 0.0), i, 0.1)

    if p.motion == 0:  # AXIS
        p.axes = [
            _attr_float(_read_attr(geo, f"prc_a{k}", 0.0), i, 0.0)
            for k in range(1, 7)
        ]
    elif p.motion == 3:  # Action / Insert Code; kind 0 stays generic.
        p.action_kind = _attr_int(_read_attr(geo, "prc_action_kind", 0), i, 0)
        p.inline_code = _attr_string(_read_attr(geo, "prc_inline_code", ""), i, "")
        p.is_comment  = _attr_bool(_read_attr(geo, "prc_is_comment", False), i, False)

        # Backward-compatibility for stale node groups: infer interrupt
        # actions from their attributes if action_kind was not stamped.
        if p.action_kind == 0:
            if _read_attr(geo, "prc_interrupt_number", None) is not None:
                p.action_kind = 5
            elif _read_attr(geo, "prc_interrupt_prio", None) is not None:
                p.action_kind = 4

        if p.action_kind == 1:
            port = _attr_int(_read_attr(geo, "prc_io_port", 1), i, 1)
            state = _attr_bool(_read_attr(geo, "prc_io_state", True), i, True)
            p.inline_code = f"$OUT[{port}] = {'TRUE' if state else 'FALSE'}"
            p.is_comment = False
        elif p.action_kind == 2:
            sec = _attr_float(_read_attr(geo, "prc_wait_sec", 0.0), i, 0.0)
            p.inline_code = f"WAIT SEC {sec:g}"
            p.is_comment = False
        elif p.action_kind == 3:
            port = _attr_int(_read_attr(geo, "prc_in_port", 1), i, 1)
            p.inline_code = f"WAIT FOR $IN[{port}]"
            p.is_comment = False
        elif p.action_kind == 4:
            # Interrupt declaration: [GLOBAL] INTERRUPT DECL Prio WHEN $IN[Port]==Cond DO Subprog
            is_global = _attr_bool(_read_attr(geo, "prc_interrupt_global", False), i, False)
            prio = _attr_int(_read_attr(geo, "prc_interrupt_prio", 23), i, 23)
            port = _attr_int(_read_attr(geo, "prc_interrupt_port", 1), i, 1)
            condition = _attr_bool(_read_attr(geo, "prc_interrupt_condition", True), i, True)
            subprog_id = _attr_int(_read_attr(geo, "prc_interrupt_subprogram_id", 1), i, 1)
            subprog_raw = _attr_string(_read_attr(geo, "prc_interrupt_subprogram", ""), i, "")

            # KUKA user priorities: 1, 2, 4..39, 81..128 (3 and 40..80 reserved).
            if prio <= 2:
                prio = max(1, prio)
            elif prio <= 39:
                prio = max(4, prio)
            elif prio <= 80:
                prio = 81
            else:
                prio = min(128, prio)

            port = max(1, port)
            subprog_id = max(1, subprog_id)
            subprog = subprog_raw.strip() or f"UP{subprog_id}"
            cond_str = "TRUE" if condition else "FALSE"
            prefix = "GLOBAL " if is_global else ""
            # Emit explicit subprogram call syntax expected by KRL.
            p.inline_code = f"{prefix}INTERRUPT DECL {prio} WHEN $IN[{port}]=={cond_str} DO {subprog} ()"
            p.is_comment = False
        elif p.action_kind == 5:
            number = _attr_int(_read_attr(geo, "prc_interrupt_number", 1), i, 1)
            enable = _attr_bool(_read_attr(geo, "prc_interrupt_enable", True), i, True)
            cmd = "ON" if enable else "OFF"
            number = int(number)
            if number > 0:
                p.inline_code = f"INTERRUPT {cmd} {number}"
            else:
                p.inline_code = f"INTERRUPT {cmd}"
            p.is_comment = False
        elif p.action_kind == 6:
            stop1 = _attr_bool(_read_attr(geo, "prc_brake_stop1", False), i, False)
            p.inline_code = "BRAKE F" if stop1 else "BRAKE"
            p.is_comment = False
    else:
        v = geo.vertices[i].co
        p.position = mathutils.Vector((v.x, v.y, v.z))
        p.orient = _attr_quat(_read_attr(geo, "prc_orient", None), i)
        if p.motion == 1:
            # Posture is stored as Int (GN can't write STRING attrs); we
            # zero-pad to 3 digits to match the protocol convention ("010").
            posture_int = _attr_int(_read_attr(geo, "prc_posture", 10), i, 10)
            p.posture = f"{max(0, posture_int):03d}"

    # Tool ID is stored as Int (same reason); empty string for the default 0.
    tool_int = _attr_int(_read_attr(geo, "prc_tool_id", 0), i, 0)
    p.tool_id = "" if tool_int == 0 else str(tool_int)
    p.group_type = _attr_int(_read_attr(geo, "prc_group_type", 1), i, 1)
    p.motion_group = _attr_int(_read_attr(geo, "prc_motion_group", 0), i, 0)
    return p


# ---------------------------------------------------------------------------
# Matrix conversion
# ---------------------------------------------------------------------------

def _build_prc_matrix(position_m: mathutils.Vector, rotation: mathutils.Quaternion) -> "prc_pb2.Matrix4x4":
    mtx = rotation.to_matrix().to_4x4()
    mtx.translation = position_m
    mtx.transpose()  # Blender (column-major) → PRC (row-major).
    m = prc_pb2.Matrix4x4()
    m.m11, m.m12, m.m13, m.m14 = mtx[0][0], mtx[0][1], mtx[0][2], mtx[0][3]
    m.m21, m.m22, m.m23, m.m24 = mtx[1][0], mtx[1][1], mtx[1][2], mtx[1][3]
    m.m31, m.m32, m.m33, m.m34 = mtx[2][0], mtx[2][1], mtx[2][2], mtx[2][3]
    m.m41 = mtx[3][0] * 1000.0
    m.m42 = mtx[3][1] * 1000.0
    m.m43 = mtx[3][2] * 1000.0
    m.m44 = mtx[3][3]
    return m


# ---------------------------------------------------------------------------
# Per-point command builders
# ---------------------------------------------------------------------------

def _build_command(p: _Point) -> "prc_pb2.MotionCommand":
    if p.motion == 0:  # AXIS
        return prc_pb2.MotionCommand(
            axis_motion=prc_pb2.AxisMotion(
                target=prc_pb2.JointTarget(
                    axis_values=p.axes,
                    speed=[p.speed],
                ),
            )
        )
    if p.motion == 1:  # PTP
        return prc_pb2.MotionCommand(
            ptp_motion=prc_pb2.PTPMotion(
                target=prc_pb2.CartesianTarget(
                    position=prc_pb2.CartesianPosition(matrix=_build_prc_matrix(p.position, p.orient)),
                    posture=p.posture or "010",
                    speed=[p.speed],
                ),
            )
        )
    # LIN
    return prc_pb2.MotionCommand(
        lin_motion=prc_pb2.LINMotion(
            target=prc_pb2.CartesianTarget(
                position=prc_pb2.CartesianPosition(matrix=_build_prc_matrix(p.position, p.orient)),
                speed=[p.speed],
            ),
        )
    )


# Allowed (group_type, motion) pairs. Anything outside this set is a wiring
# mistake — e.g. a LIN command inside a PTP Motion Group, or a PTP command
# inside a Cartesian Motion Group.
#   group_type 0 (CP)     → motion 2 (LIN)
#   group_type 1 (PTP)    → motion 0 (AXIS) or motion 1 (PTP)
#   group_type 2 (Action) → motion 3 (Action)
_ALLOWED_GROUP_MOTIONS: dict[int, frozenset[int]] = {
    0: frozenset({2}),
    1: frozenset({0, 1}),
    2: frozenset({3}),
}

_GROUP_TYPE_NAMES = {0: "Cartesian", 1: "PTP", 2: "Action"}
_MOTION_NAMES = {0: "AXIS", 1: "PTP", 2: "LIN", 3: "Action"}


def _validate_group_motions(group_type: int, points: list[_Point]) -> None:
    allowed = _ALLOWED_GROUP_MOTIONS.get(group_type)
    if allowed is None:
        raise RuntimeError(f"Unknown prc_group_type {group_type}.")
    for p in points:
        if p.motion not in allowed:
            raise RuntimeError(
                f"{_MOTION_NAMES.get(p.motion, str(p.motion))} command found "
                f"inside a {_GROUP_TYPE_NAMES[group_type]} motion group. "
                f"Wrap LIN moves in PRC Cartesian Motion Group, AXIS / PTP "
                f"moves in PRC PTP Motion Group, and Insert Code in PRC "
                f"Action Group."
            )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_task_from_carrier(scene) -> "prc_pb2.Task":
    carrier = bpy.data.objects.get(_ng.CARRIER_OBJECT_NAME)
    if carrier is None:
        raise RuntimeError(
            f"Carrier object '{_ng.CARRIER_OBJECT_NAME}' not found. "
            f"Press 'Generate Geometry Node Groups' first."
        )

    deps = bpy.context.evaluated_depsgraph_get()
    geo = carrier.evaluated_get(deps).data
    n = len(geo.vertices)
    if n == 0:
        raise RuntimeError(
            "PRC_Program has no points. Wire motion commands into PRC Task."
        )

    # Preserve the evaluated point order exactly: split into contiguous runs
    # whenever (group_type, tool_id, motion_group) changes. This makes the
    # generated program follow the order produced by the final Join Geometry
    # output, which is the most intuitive behaviour for authored node trees.
    groups: list[tuple[int, str, list[_Point]]] = []
    subprog_id_attr = _function_subprogram_attr(geo)
    for i in range(n):
        # Skip points tagged by a PRC Function Definition node — they belong
        # to a subprogram body (DEF UPx) and are injected at export time.
        if _attr_int(subprog_id_attr, i, 0) > 0:
            continue
        p = _read_point(geo, i)
        if not groups:
            groups.append((p.group_type, p.tool_id, [p]))
            continue

        last_group_type, last_tool_id, last_points = groups[-1]
        last_mg = last_points[-1].motion_group
        if (
            p.group_type == last_group_type
            and p.tool_id == last_tool_id
            and p.motion_group == last_mg
        ):
            last_points.append(p)
        else:
            groups.append((p.group_type, p.tool_id, [p]))

    # Task name and type are fixed for the v1 add-on. The corresponding
    # scene properties still exist for backward compatibility with older
    # .blend files but are no longer surfaced in the UI.
    task = prc_pb2.Task(
        name="Task",
        type=prc_pb2.TaskType.SIMULATE_AND_EXECUTE_TASK,
    )

    for group_type, tool_id, points in groups:
        _validate_group_motions(group_type, points)

        if group_type == 2:
            # Action group — emit one TaskPayload per action waypoint.
            for p in points:
                action = prc_pb2.Action(
                    insert_code_action=prc_pb2.InsertCode(
                        code=[p.inline_code],
                        is_comment=p.is_comment,
                    ),
                )
                task.payload.append(prc_pb2.TaskPayload(action_task=action))
            continue

        commands = [_build_command(p) for p in points]
        if not commands:
            continue
        if group_type == 1:
            interpolation = "C_PTP"
            mg_type = prc_pb2.MotionGroupType.PTP
        else:
            interpolation = "C_DIS"
            mg_type = prc_pb2.MotionGroupType.CP
        # robot_base is intentionally NOT set — the server uses the base
        # configured via the WebUI / settings dictionary. Sending an explicit
        # identity here would override the user's WebUI base change.
        mg = prc_pb2.MotionGroup(
            commands=commands,
            interpolation=interpolation,
            tool_id=tool_id or "",
            motion_group_type=mg_type,
        )
        task.payload.append(prc_pb2.TaskPayload(motion_group_task=mg))

    return task


def collect_function_definitions_from_carrier(scene) -> "dict[int, list[str]]":
    """Return a mapping of subprogram ID → ordered list of KRL code lines.

    Points tagged with ``prc_function_subprogram_id > 0`` (or legacy
    ``prc_function_id > 0``) by a
    *PRC Function Definition* node group are collected here, grouped by ID
    in their evaluated order, and returned so the export operator can inject:

        DEF UP{ID} ()
        <lines>
        END

    after the main program's closing END.
    """
    carrier = bpy.data.objects.get(_ng.CARRIER_OBJECT_NAME)
    if carrier is None:
        return {}

    deps = bpy.context.evaluated_depsgraph_get()
    geo = carrier.evaluated_get(deps).data
    n = len(geo.vertices)
    if n == 0:
        return {}

    subprog_id_attr = _function_subprogram_attr(geo)
    if subprog_id_attr is None:
        return {}

    result: dict[int, list[str]] = {}
    for i in range(n):
        sid = _attr_int(subprog_id_attr, i, 0)
        if sid <= 0:
            continue
        p = _read_point(geo, i)
        if p.motion != 3:
            continue  # Only action-type points are collected as KRL lines
        line = p.inline_code
        if not line:
            continue
        if sid not in result:
            result[sid] = []
        result[sid].append(line)

    return result
