from measurements.infrastructure.postgres.repository import _valid_rpm

def test_rpm_validity_is_independent_of_motor_torque_validity():
    assert _valid_rpm({"valid": True, "rpm_mpu": 0}) is None
    assert _valid_rpm({"valid": True, "rpm_mpu": 0, "rpm_observation_valid": False}) is None
    assert _valid_rpm({"valid": True, "rpm_mpu": 6000, "rpm_observation_valid": False}) is None
    assert _valid_rpm({"valid": True, "rpm_mpu": 6000}) == 6000
    assert _valid_rpm({"valid": False, "rpm_mpu": 0, "rpm_observation_valid": True}) == 0
    assert _valid_rpm({"rpm_mpu": False, "rpm_observation_valid": True}) is None
