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
        await asyncio.sleep(5)


#        for device in controller.devices:
#            print(f"Status: {device}")


async def main(controller: GoveeController):
    await controller.start()
    await asyncio.sleep(5)

    device = controller.get_device_by_sku("H618A")
    if device:
        await device.turn_on()
    await print_status(controller)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    controller: GoveeController = GoveeController(
        loop=loop,
        listening_address="10.0.0.52",
        discovery_enabled=False,
        discovered_callback=discovered_callback,
        evicted_callback=lambda device: print(f"Evicted {device}"),
    )

    controller.add_device("10.0.0.229")
    try:
        loop.run_until_complete(main(controller))
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print("Closing Loop")
        controller.cleanup()
        loop.close()
