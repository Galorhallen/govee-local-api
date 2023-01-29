import asyncio
import functools

from govee_local_api import GoveeController, GoveeDevice
  
def discovered_callback(device: GoveeDevice, is_new: bool):
  if is_new:
    print(f'Discovered: {device}. New: {is_new}')

async def print_status(controller: GoveeController):
  while True:
    for device in controller.devices:
      print(f'Status: {device}')
    await asyncio.sleep(5)


async def main(controller: GoveeController):    
  await controller.start()
  await asyncio.sleep(5)

  device: GoveeDevice = controller.get_device_by_sku("H615A")
  await device.turn_on()
  await print_status(controller)


if __name__ == '__main__':
  loop = asyncio.new_event_loop()
  controller: GoveeController = GoveeController(
      loop,
      autodiscovery=True,
      discovered_callback=discovered_callback,
      evicted_callback=lambda device: print(f'Evicted {device}')
    )

  try:
    loop.run_until_complete(main(controller))
    loop.run_forever()
  except KeyboardInterrupt:
    pass
  finally:
    print("Closing Loop")
    controller.clenaup()
    loop.close()
