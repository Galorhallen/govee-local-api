import asyncio

from govee_local_api import GoveeController, GoveeDevice


def update_device_callback(device: GoveeDevice):
    print(f"Goveee device update callback: {device}")


def discovered_callback(device: GoveeDevice, is_new: bool) -> bool:
    if is_new:
        print(f"Discovered: {device}. New: {is_new}")
        device.set_update_callback(update_device_callback)
    return True


async def print_status(controller: GoveeController, device: GoveeDevice):
    while True:
        if not device or not device.capabilities:
            continue
        for seg in range(1, 1 + device.capabilities.segments_count):
            await device.set_segment_color(seg, (255, 0, 0))
            await asyncio.sleep(0.1)
        for seg in range(1, 1 + device.capabilities.segments_count):
            await device.set_segment_color(seg, (0, 0, 255))
            await asyncio.sleep(0.1)
        await asyncio.sleep(1)


async def main(controller: GoveeController):
    await controller.start()
    print("start")
    await asyncio.sleep(1)
    print("Waited")

    device = controller.get_device_by_ip("10.0.0.110")
    if not device:
        print("Device not found")
    await device.turn_on()
    await device.set_rgb_color(255, 255, 255)
    await device.set_brightness(100)
    await asyncio.sleep(1)

    await print_status(controller, device)


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
