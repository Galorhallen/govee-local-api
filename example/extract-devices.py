from govee_local_api.light_capabilities import GOVEE_LIGHT_CAPABILITIES

if __name__ == "__main__":
    models = [key for key in GOVEE_LIGHT_CAPABILITIES.keys()]

    print("Supported Govee light models:")
    print(",\n".join(sorted(models)))
