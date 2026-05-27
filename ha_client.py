import json
import requests
from typing import List, Dict, Any, Tuple, Set

class HomeAssistantClient:
    def __init__(self, url: str, token: str):
        # Normalize url: remove trailing slash
        self.url = url.rstrip('/')
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def test_connection(self) -> Tuple[bool, str]:
        """
        Validates the connection to Home Assistant API.
        Returns (success, message).
        """
        try:
            response = requests.get(f"{self.url}/api/", headers=self.headers, timeout=5)
            if response.status_code == 200:
                data = response.json()
                msg = data.get("message", "API running.")
                return True, f"Success: Connected. {msg}"
            elif response.status_code == 401:
                return False, "Error: Unauthorized. Check your Long-Lived Access Token."
            else:
                return False, f"Error: Status code {response.status_code} from HA API."
        except requests.exceptions.Timeout:
            return False, "Error: Connection timed out. Check the URL and network."
        except requests.exceptions.ConnectionError:
            return False, "Error: Could not connect to the Home Assistant server. Check the URL."
        except Exception as e:
            return False, f"Error: {str(e)}"

    def get_entities(self) -> List[Dict[str, Any]]:
        """
        Fetches all controllable entities from Home Assistant, resolving areas and labels
        via the WebSocket API registry and combining them with state details.
        """
        # 1. Dynamically determine controllable domains by fetching services
        controllable_domains = set()
        try:
            response = requests.get(f"{self.url}/api/services", headers=self.headers, timeout=10)
            if response.status_code == 200:
                services_list = response.json()
                for service_group in services_list:
                    dom = service_group.get("domain")
                    # Filter out purely diagnostics or system services
                    if dom and dom not in ["persistent_notification", "system_log", "logger", "recorder", "zone", "person"]:
                        controllable_domains.add(dom)
        except Exception as e:
            print(f"Error fetching services dynamically: {e}")

        # Fallback to standard ones if we failed to fetch
        if not controllable_domains:
            controllable_domains = {
                "light", "switch", "button", "media_player", "climate", "script", 
                "automation", "input_boolean", "fan", "cover", "lock", "scene", "input_button"
            }
        
        # 2. Fetch REST active states
        states = []
        try:
            response = requests.get(f"{self.url}/api/states", headers=self.headers, timeout=10)
            if response.status_code == 200:
                states = response.json()
        except Exception as e:
            print(f"Error fetching states via REST: {e}")
            return []

        if not states:
            return []

        # 3. Fetch registries via WebSocket
        areas_dict = {}
        devices_dict = {}
        labels_dict = {}
        entity_registry_dict = {}

        try:
            import websocket
            ws_url = self.url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
            ws = websocket.create_connection(ws_url, timeout=5)
            
            # Wait for auth required
            init_resp = json.loads(ws.recv())
            
            # Send authentication
            ws.send(json.dumps({
                "type": "auth",
                "access_token": self.token
            }))
            auth_resp = json.loads(ws.recv())
            
            if auth_resp.get("type") == "auth_ok":
                msg_id = 1
                
                def query_ws(cmd_type):
                    nonlocal msg_id
                    cmd = {"id": msg_id, "type": cmd_type}
                    msg_id += 1
                    ws.send(json.dumps(cmd))
                    resp_data = json.loads(ws.recv())
                    if resp_data.get("success"):
                        return resp_data.get("result", [])
                    return []

                areas = query_ws("config/area_registry/list")
                devices = query_ws("config/device_registry/list")
                labels = query_ws("config/label_registry/list")
                entities_reg = query_ws("config/entity_registry/list")

                areas_dict = {a["area_id"]: a["name"] for a in areas if "area_id" in a}
                devices_dict = {d["id"]: {"area_id": d.get("area_id"), "labels": d.get("labels", [])} for d in devices if "id" in d}
                labels_dict = {l["label_id"]: l["name"] for l in labels if "label_id" in l}
                
                entity_registry_dict = {
                    e["entity_id"]: {
                        "area_id": e.get("area_id"),
                        "device_id": e.get("device_id"),
                        "labels": e.get("labels", []),
                        "categories": list(e.get("categories", {}).values())
                    }
                    for e in entities_reg if "entity_id" in e
                }
            ws.close()
        except Exception as ws_ex:
            print(f"Error querying HA registries via WebSocket: {ws_ex}. Falling back to default list.")

        # 4. Combine active states with registry metadata
        detailed_entities = []
        for state_obj in states:
            entity_id = state_obj.get("entity_id", "")
            if not entity_id or "." not in entity_id:
                continue
            
            domain = entity_id.split(".")[0]
            if domain not in controllable_domains:
                continue
                
            attributes = state_obj.get("attributes", {})
            friendly_name = attributes.get("friendly_name", entity_id)
            state = state_obj.get("state", "unknown")
            
            # Lookup registry metadata
            reg_info = entity_registry_dict.get(entity_id, {})
            area_id = reg_info.get("area_id")
            device_id = reg_info.get("device_id")
            labels_list = list(reg_info.get("labels", []))
            categories_list = list(reg_info.get("categories", []))
            
            # Inherit area and labels from device if not set directly on entity
            if not area_id and device_id:
                dev_info = devices_dict.get(device_id, {})
                area_id = dev_info.get("area_id")
                # Merge device labels
                for dl in dev_info.get("labels", []):
                    if dl not in labels_list:
                        labels_list.append(dl)
                        
            # Resolve area name
            area_name = areas_dict.get(area_id, "No Area") if area_id else "No Area"
            
            # Resolve label names
            friendly_labels = [labels_dict.get(lid, lid) for lid in labels_list]
            
            detailed_entities.append({
                "entity_id": entity_id,
                "friendly_name": friendly_name,
                "domain": domain,
                "state": state,
                "area_id": area_id or "",
                "area_name": area_name,
                "labels": friendly_labels,
                "categories": categories_list
            })
            
        detailed_entities.sort(key=lambda x: x["friendly_name"].lower())
        return detailed_entities

    def get_services_for_domain(self, domain: str) -> List[str]:
        """
        Fetches available services for a specific domain from Home Assistant.
        If HA services call fails, returns a set of standard sensible defaults.
        """
        defaults = {
            "light": ["turn_on", "turn_off", "toggle"],
            "switch": ["turn_on", "turn_off", "toggle"],
            "button": ["press"],
            "input_button": ["press"],
            "media_player": ["turn_on", "turn_off", "toggle", "volume_up", "volume_down", "media_play_pause", "media_next_track", "media_previous_track"],
            "climate": ["set_hvac_mode", "set_temperature"],
            "script": ["turn_on"],
            "automation": ["trigger", "turn_on", "turn_off"],
            "input_boolean": ["turn_on", "turn_off", "toggle"],
            "fan": ["turn_on", "turn_off", "toggle", "increase_speed", "decrease_speed"],
            "cover": ["open_cover", "close_cover", "stop_cover", "toggle"],
            "lock": ["lock", "unlock"],
            "scene": ["turn_on"]
        }
        
        try:
            response = requests.get(f"{self.url}/api/services", headers=self.headers, timeout=10)
            if response.status_code == 200:
                services_list = response.json()
                for service_group in services_list:
                    if service_group.get("domain") == domain:
                        services = list(service_group.get("services", {}).keys())
                        # If we got valid services, return them
                        if services:
                            services.sort()
                            return services
        except Exception as e:
            print(f"Error fetching services from HA API: {e}")
            
        # Fallback to defaults
        return defaults.get(domain, ["turn_on", "turn_off", "toggle"])

    def call_service(self, domain: str, service: str, entity_id: str) -> Tuple[bool, str]:
        """
        Triggers a service call in Home Assistant.
        Returns (success, message).
        """
        url = f"{self.url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id}
        
        try:
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            if response.status_code in [200, 201]:
                return True, f"Successfully triggered {domain}.{service} on {entity_id}"
            else:
                return False, f"Failed: status code {response.status_code}. Response: {response.text}"
        except Exception as e:
            return False, f"Error calling service: {str(e)}"
