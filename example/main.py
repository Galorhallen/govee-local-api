import asyncio

from govee_local_api import GoveeController, GoveeDevice


def update_device_callback(device: GoveeDevice):
    print(f"Goveee device update callback: {device}")


def discovered_callback(device: GoveeDevice, is_new: bool) -> bool:
    if is_new:
        print(f"Discovered: {device}. New: {is_new}")
        device.set_update_callback(update_device_callback)
    return True


async def print_status(controller: GoveeController):
    while True:
        if not controller.devices:
            print("No devices found")
        for device in controller.devices:
            print(f"Status: {device}")
        await asyncio.sleep(5)


async def main(controller: GoveeController):
    await controller.start()
    print("start")
    await asyncio.sleep(1)
    print("Waited")

    devices = [controller.get_device_by_ip("10.0.0.110")]
    # devices = controller.devices
    for device in devices:
        if not device:
            continue
        await device.turn_on()
        await asyncio.sleep(1)
        await device.set_segment_color(1, (255, 0, 0))
        # await device.set_segment_color(14, (0, 255, 0))
        # await device.set_segment_color(13, (0, 0, 255))
        # await device.set_segment_color(12, (255, 255, 0))
        # await device.set_segment_color(11, (0, 255, 255))
        # await device.set_segment_color(10, (255, 0, 255))
        # await device.set_segment_color(9, (0, 0, 0))

    await print_status(controller)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    controller: GoveeController = GoveeController(
        loop=loop,
        listening_address="0.0.0.0",
        discovery_enabled=True,
        discovered_callback=discovered_callback,
        evicted_callback=lambda device: print(f"Evicted {device}"),
    )

    try:
        loop.run_until_complete(main(controller))
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Closing Loop")
        controller.cleanup()
        loop.close()
