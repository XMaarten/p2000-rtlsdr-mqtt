from p2000_receiver.config import ReceiverConfig
from p2000_receiver.health import receiver_is_healthy


def test_multimon_health_requires_both_receiver_processes():
    config = ReceiverConfig(decoder='multimon')
    healthy = [
        ('/usr/bin/rtl_fm', '-f', '169.65M'),
        ('/usr/local/bin/multimon-ng', '-q', '-a', 'FLEX'),
    ]
    assert receiver_is_healthy(config, healthy)
    assert not receiver_is_healthy(config, healthy[:1])


def test_deflex_health_matches_configured_command_not_generic_python():
    config = ReceiverConfig(
        decoder='deflex',
        deflex_command=['python3', '/opt/deflex/flex_receiver.py', '--live'],
    )
    assert receiver_is_healthy(
        config,
        [('/usr/local/bin/python3', '/opt/deflex/flex_receiver.py', '--live')],
    )
    assert not receiver_is_healthy(config, [('python3', '/some/other/script.py')])
