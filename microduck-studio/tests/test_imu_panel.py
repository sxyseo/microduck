"""Frontend contract for the IMU bench panel (web/imu-studio.js).

The panel reads the imu_to_dxl node (bus ID 200) with Web Serial, so there is no backend to
test — these assertions pin the protocol contract (FT6 15-byte block at 56..70), the safety
notes, and the registration points other files rely on.
"""

from pathlib import Path

WEB = Path(__file__).parents[1] / "web"


def panel_js() -> str:
    return (WEB / "imu-studio.js").read_text(encoding="utf-8")


def test_index_registers_script_and_inits_before_studio() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'src="/assets/imu-studio.js' in html
    # The card must exist before Studio.init() builds the bench tab bar from it.
    assert html.index("window.ImuPanel.init();") < html.index("window.Studio.init();")


def test_bench_tab_registered_in_studio() -> None:
    js = (WEB / "studio.js").read_text(encoding="utf-8")
    assert "['imu','IMU 姿态']" in js


def test_css_styles_the_card() -> None:
    css = (WEB / "studio.css").read_text(encoding="utf-8")
    assert "#card-imu .imu-fields" in css
    assert "#card-imu .imu-actions" in css


def test_reads_ft6_contract_block_at_56() -> None:
    js = panel_js()
    assert "ADDR_BLOCK = 56, BLOCK_LEN = 15" in js
    assert "transact(sid, 0x02, [ADDR_BLOCK, BLOCK_LEN], BLOCK_LEN)" in js
    # ±500 dps gyro scale and binary16 quaternion with w reconstructed on the host.
    assert "GYRO_DPS_PER_COUNT = 0.0175" in js
    assert "Math.sqrt(Math.max(0, 1 - norm2))" in js


def test_holds_last_valid_attitude_instead_of_zero_quaternion() -> None:
    js = panel_js()
    # All-zero quaternion bytes or the not-ready bit mean the fusion has not converged yet.
    assert "(st & 0x01) || (!qx && !qy && !qz) || norm2 > 1.001" in js
    assert "上一份有效姿态" in js


def test_detects_stale_and_frozen_data() -> None:
    js = panel_js()
    assert "st & 0x02 ? '数据过期' : '数据新鲜'" in js
    assert "疑似冻结" in js  # three consecutive identical sample counts


def test_default_node_id_is_200() -> None:
    assert 'id="imu-id" type="number" min="0" max="252" value="200"' in panel_js()


def test_warns_on_nonzero_reserved_byte() -> None:
    js = panel_js()
    assert "d[14] !== 0" in js
    assert "FT6 契约应为 0" in js


def test_static_drift_check_uses_doc_gate() -> None:
    js = panel_js()
    assert "DRIFT_LIMIT_DPS = 2.865" in js  # 0.05 rad/s,deep-dive/68 验收门槛
    assert "静态零漂检查" in js


def test_bus_safety_notes_are_present() -> None:
    js = panel_js()
    # One bus master at a time: robotd must be stopped, URT2 console shares the port.
    assert "robotd 已停止" in js
    assert "URT2 调试台与本面板共用物理串口" in js
    assert "'serial' in navigator" in js
