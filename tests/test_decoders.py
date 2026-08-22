from p2000_receiver.config import ReceiverConfig
from p2000_receiver.decoders import build_rtl_command


def test_rtl_command_accepts_device_serial_number():
    config = ReceiverConfig(device="00000169")
    command = build_rtl_command(config)
    index = command.index("-d")
    assert command[index + 1] == "00000169"
