import yaml

def get_recorder_yaml(board: str, pin: str, led_pin: str = "") -> str:
    """
    Generates ESPHome YAML config for the recording mode.
    This config is compiled and uploaded to the ESP32 to capture IR codes over Serial.
    """
    yaml_str = f"""# ESPHome Configuration for IR Recording
esphome:
  name: esp32-ir-recorder

esp32:
  board: {board}
  framework:
    type: arduino

logger:
  baud_rate: 115200
"""

    if led_pin and led_pin.lower() != "none":
        yaml_str += f"""
output:
  - platform: gpio
    id: onboard_led
    pin: {led_pin}
"""

    yaml_str += f"""
remote_receiver:
  pin: {pin}
  dump: all
"""

    if led_pin and led_pin.lower() != "none":
        yaml_str += """  on_raw:
    then:
      - output.turn_on: onboard_led
      - delay: 100ms
      - output.turn_off: onboard_led
"""
    return yaml_str

def get_final_yaml(board: str, wifi_ssid: str, wifi_password: str, pin: str, mappings: list, led_pin: str = "") -> str:
    """
    Generates ESPHome YAML config for the final standalone mode.
    This config connects to Wi-Fi, enables the Native HA API, and maps IR codes
    directly to Home Assistant service calls.
    """
    yaml_lines = [
        "# ESPHome Configuration for Standalone IR Remote Receiver",
        "esphome:",
        "  name: esp32-ir-receiver",
        "",
        "esp32:",
        f"  board: {board}",
        "  framework:",
        "    type: arduino",
        "",
        "wifi:",
        f'  ssid: "{wifi_ssid}"',
        f'  password: "{wifi_password}"',
        "  ap:",
        '    ssid: "IR-Receiver Fallback Hotspot"',
        "",
        "api:",
        "",
        "ota:",
        "  - platform: esphome",
        "",
        "logger:",
        "  baud_rate: 115200",
        ""
    ]

    # Add LED output if configured
    if led_pin and led_pin.lower() != "none":
        yaml_lines.extend([
            "output:",
            "  - platform: gpio",
            "    id: onboard_led",
            f"    pin: {led_pin}",
            ""
        ])

    # Add remote receiver config
    yaml_lines.extend([
        "remote_receiver:",
        f"  pin: {pin}",
        "  dump: all"
    ])

    # Blink LED on any incoming raw signal if configured
    if led_pin and led_pin.lower() != "none":
        yaml_lines.extend([
            "  on_raw:",
            "    then:",
            "      - output.turn_on: onboard_led",
            "      - delay: 100ms",
            "      - output.turn_off: onboard_led"
        ])

    yaml_lines.extend([
        "",
        "binary_sensor:"
    ])

    for m in mappings:
        name = m.get("name", "Unnamed Button")
        protocol = m.get("protocol", "").upper()
        data = m.get("data", {})
        entity_id = m.get("entity_id", "")
        service = m.get("service", "")
        
        yaml_lines.append(f"  - platform: remote_receiver")
        yaml_lines.append(f'    name: "{name}"')
        
        if protocol == "NEC":
            addr = data.get("address", "0x0000")
            cmd = data.get("command", "0x0000")
            yaml_lines.append("    nec:")
            yaml_lines.append(f"      address: {addr}")
            yaml_lines.append(f"      command: {cmd}")
            
        elif protocol == "PANASONIC":
            addr = data.get("address", "0x0000")
            cmd = data.get("command", "0x0000")
            yaml_lines.append("    panasonic:")
            yaml_lines.append(f"      address: {addr}")
            yaml_lines.append(f"      command: {cmd}")
            
        elif protocol in ["SAMSUNG", "SONY", "LG"]:
            code_val = data.get("data", "0x0")
            nbits = data.get("nbits", 32)
            yaml_lines.append(f"    {protocol.lower()}:")
            yaml_lines.append(f"      data: {code_val}")
            if nbits:
                yaml_lines.append(f"      nbits: {nbits}")
                
        elif protocol == "PRONTO":
            pronto_data = data.get("data", "")
            yaml_lines.append("    pronto:")
            yaml_lines.append(f'      data: "{pronto_data}"')
            yaml_lines.append("      delta: 300")
                
        elif protocol == "RAW":
            raw_code = data.get("raw_code", [])
            raw_str = ", ".join(map(str, raw_code))
            yaml_lines.append("    raw:")
            yaml_lines.append(f"      code: [{raw_str}]")
            
        else:
            raw_code = data.get("raw_code", [])
            if raw_code:
                raw_str = ", ".join(map(str, raw_code))
                yaml_lines.append("    raw:")
                yaml_lines.append(f"      code: [{raw_str}]")
            else:
                yaml_lines.pop() # remove name
                yaml_lines.pop() # remove platform
                continue
                
        yaml_lines.append("    on_press:")
        yaml_lines.append("      then:")
        
        # Support both single service mapping (legacy) and multiple services mapping
        actions = m.get("actions", [])
        if not actions and entity_id and service:
            actions = [{"entity_id": entity_id, "service": service}]
            
        for act in actions:
            act_entity = act.get("entity_id", "")
            act_service = act.get("service", "")
            yaml_lines.append("        - homeassistant.service:")
            yaml_lines.append(f"            service: {act_service}")
            yaml_lines.append("            data:")
            yaml_lines.append(f"              entity_id: {act_entity}")
            
        yaml_lines.append("")

    return "\n".join(yaml_lines)
