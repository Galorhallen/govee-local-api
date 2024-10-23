import asyncio
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.shortcuts import clear

from govee_local_api import GoveeController, GoveeDevice, GoveeLightFeatures


def update_device_callback(device: GoveeDevice) -> None:
    # print(f"Goveee device update callback: {device}")
    pass


def discovered_callback(device: GoveeDevice, is_new: bool) -> bool:
    if is_new:
        # print(f"Discovered: {device}. New: {is_new}")
        device.set_update_callback(update_device_callback)
    return True


async def create_controller() -> GoveeController:
    controller = GoveeController(
        loop=asyncio.get_event_loop(),
        listening_address="0.0.0.0",
        discovery_enabled=True,
        discovered_callback=discovered_callback,
        evicted_callback=lambda device: print(f"Evicted {device}"),
    )
    await controller.start()
    while not controller.devices:
        print("Waiting for devices... ")
        await asyncio.sleep(1)
    print("Devices: ", [str(d) for d in controller.devices])
    return controller


async def menu(device: GoveeDevice) -> None:
    print("\nDevice: ", device)
    print("Select an option:")
    print("1. Turn on")
    print("2. Turn off")
    print("3. Set brightness (0-100)")
    print("4. Set color (R G B)")
    print("5. Set segment color (Segment, R G B)")
    print("6. Set scene")
    print("7. Send raw hex")
    print("8. Clear screen")
    print("9. Clear Device")
    print("10. Exit")


async def handle_turn_on(device: GoveeDevice) -> None:
    print("Turning on the LED strip...")
    await device.turn_on()


async def handle_turn_off(device: GoveeDevice) -> None:
    print("Turning off the LED strip...")
    await device.turn_off()


async def handle_set_brightness(device: GoveeDevice, session: PromptSession) -> None:
    while True:
        brightness = await session.prompt_async("Enter brightness (0-100): ")
        try:
            brightness = int(brightness)
            if 0 <= brightness <= 100:
                print(f"Setting brightness to {brightness}%")
                await device.set_brightness(brightness)
                break
            else:
                print("Please enter a value between 0 and 100.")
        except ValueError:
            print("Invalid input, please enter an integer.")


async def handle_set_color(device: GoveeDevice, session: PromptSession) -> None:
    while True:
        color = await session.prompt_async("Enter color (R G B, values 0-255): ")
        try:
            r, g, b = map(int, color.split())
            if all(0 <= v <= 255 for v in [r, g, b]):
                print(f"Setting color to RGB({r}, {g}, {b})")
                await device.set_rgb_color(r, g, b)
                break
            else:
                print("RGB values must be between 0 and 255.")
        except ValueError:
            print("Invalid input, please enter three integers separated by spaces.")


async def handle_set_segment_color(device: GoveeDevice, session: PromptSession) -> None:
    if device.capabilities.features & GoveeLightFeatures.SEGMENT_CONTROL == 0:
        print("This device does not support segment control.")
        return
    while True:
        segment = await session.prompt_async(
            f"Enter segment number (1-{device.capabilities.segments_count}): "
        )
        try:
            segment = int(segment)
            if 1 <= segment <= device.capabilities.segments_count:
                color = await session.prompt_async(
                    "Enter segment color (R G B, values 0-255): "
                )
                r, g, b = map(int, color.split())
                if all(0 <= v <= 255 for v in [r, g, b]):
                    print(f"Setting segment {segment} color to RGB({r}, {g}, {b})")
                    await device.set_segment_rgb_color(segment, r, g, b)
                    break
                else:
                    print("RGB values must be between 0 and 255.")
            else:
                print(
                    f"Segment number must be between 1 and {device.capabilities.segments_count}."
                )
        except ValueError:
            print(
                "Invalid input. Please enter an integer for the segment and three integers for the color."
            )


async def handle_set_scene(device: GoveeDevice, session: PromptSession):
    while True:
        scenes = device.capabilities.available_scenes
        for idx, scene in enumerate(scenes, 1):
            print(f"{idx}: {scene}")

        scene = await session.prompt_async(
            f"Enter scene number (1-{len(scenes) - 1}): "
        )
        scene_name = scenes[int(scene) - 1]
        if scene_name in device.capabilities.available_scenes:
            print(f"Setting scene to {scene}")
            await device.set_scene(scene)
            break
        else:
            print("Invalid scene. Please choose from the available scenes.")


async def handle_clear_screen(device):
    clear()


async def handle_exit(device):
    print("Exiting...")
    raise SystemExit()


async def devices_menu(session, devices: list[GoveeDevice]) -> GoveeDevice:
    selection = None
    devices = sorted(devices, key=lambda d: d.sku)
    while (
        selection is None
        or selection == ""
        or not selection.isnumeric()
        or int(selection) >= len(devices)
    ):
        for idx, device in enumerate(devices):
            print(f"{idx}: {device.ip} - {device.sku}")
        selection = await session.prompt_async(
            f"Choose an option (0-{len(devices) - 1}): "
        )
        if not selection.isnumeric():
            continue
    print(f"Selected device: {selection}")
    return devices[int(selection)]


async def handle_send_hex(device: GoveeDevice, session: PromptSession) -> None:
    hex_data = await session.prompt_async("Enter hex data: ")
    await device.send_raw_command(hex_data)


async def repl() -> None:
    session = PromptSession()
    print("Welcome to the LED Control REPL.")

    # Dictionary of command handlers
    command_handlers = {
        "1": handle_turn_on,
        "2": handle_turn_off,
        "3": lambda device: handle_set_brightness(device, session),
        "4": lambda device: handle_set_color(device, session),
        "5": lambda device: handle_set_segment_color(device, session),
        "6": lambda device: handle_set_scene(device, session),
        "7": lambda device: handle_send_hex(device, session),
        "8": handle_clear_screen,
        "10": handle_exit,
    }

    controller: GoveeController = await create_controller()
    selected_device: GoveeDevice | None = None

    while True:
        if not selected_device:
            selected_device = await devices_menu(session, controller.devices)

        await menu(selected_device)
        with patch_stdout():
            user_choice = await session.prompt_async("Choose an option (1-10): ")
            if user_choice == "9":
                selected_device = None
                continue

        # Get the command handler from the dictionary, or return an invalid message if not found
        handler = command_handlers.get(user_choice)
        if handler:
            await handler(selected_device)  # Call the appropriate command handler
        else:
            print("Invalid option, please try again.")


async def main():
    await repl()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (EOFError, KeyboardInterrupt):
        print("REPL exited.")
