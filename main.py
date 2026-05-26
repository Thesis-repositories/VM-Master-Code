import asyncio
from fastapi import FastAPI, Request, HTTPException
import subprocess
import json
from proxmoxer import ProxmoxAPI
import time
import os
from dotenv import load_dotenv

load_dotenv()

proxmox = ProxmoxAPI(
    os.getenv("host"), user=os.getenv("user"),
    token_name=os.getenv("token_name"), token_value=os.getenv("token_value"), verify_ssl=False
    )

app = FastAPI()
lock = asyncio.Lock()

def load_trusted_ips():
    with open("addresses.json", "r") as f:
        data = json.load(f)
    return {entry["ip"] for entry in data["addresses"]}

TRUSTED_IPS = load_trusted_ips()

@app.middleware("http")
async def check_ip(request: Request, call_next):
    if request.client.host not in TRUSTED_IPS:
        raise HTTPException(status_code=403)
    return await call_next(request)

@app.get("/")
def tryProxmoxApi():
    vmid = 101
    resources = proxmox.cluster().resources().get()
    for item in resources:
        if 'vmid' in item:
            if item['vmid'] == vmid:
                output = item
                break

    return {'output': output}

@app.get("/config")
async def generateRegistrationToken():
    token = subprocess.run(["bash", "./create-runner.sh"], capture_output=True, text=True)
    return {
        "token": token.stdout.strip(),
        "org_url": "https://github.com/" + os.getenv("ORG")
    }

@app.post("/create-runner")
async def createNewVM():
    async with lock:
        vmid = 104
        newvmid = proxmox.cluster().nextid().get()
        node = "andromeda"

        ip, mac, found = getAddresses()
        message = "No available ip found"
        if found:
            hostname = os.getenv("basic_name") + str(newvmid)
            upid = proxmox.nodes(node).lxc(vmid).clone().post(newid=newvmid, node=node, hostname=hostname, full=1)
            try:
                await waitTask(node, upid)
            except TimeoutError as e:
                return {"message": str(e)}, 504
            except RuntimeError as e:
                return {"message": str(e)}, 500
            upid = proxmox.nodes(node).lxc(newvmid).config.put(
                net0= (
                    "name=eth0,"
                    "bridge=vmbr0,"
                    "hwaddr="+mac+","
                    "ip="+ip+"/24"+","
                    "gw="+os.getenv("gateway")
                )
            )
            proxmox.nodes(node).lxc(newvmid).status().start().post()
            found = setOccupied(ip, newvmid, node)
            message = "LXC created; ip allocated: " + str(found)

        return {"message": message}


@app.delete("/destroy-runner")
async def destroyRunner(request: Request):
    async with lock:
        ip = request.client.host
        vmid, node, found = setAddressesFreeAndUpload(ip)
        if found:
            upid = proxmox.nodes(node).lxc(vmid).status().stop().post()
            try:
                await waitTask(node, upid)
            except TimeoutError as e:
                return {"message": str(e)}, 504
            except RuntimeError as e:
                return {"message": str(e)}, 500
            proxmox.nodes(node).lxc(vmid).delete()
            message = "Eliminated succesfully"
        else:
            message = "Received request from: " + ip + " but it has not been found"
        return {"message": message}

def getAddresses():
    with open("addresses.json", "r") as f:
        data = json.load(f)
        
    found = False
    for i in range(len(data["addresses"])):
        if (data["addresses"][i]["vmid"] == None):
            ip = data["addresses"][i]["ip"]
            mac = data["addresses"][i]["mac"]
            found = True
            break
    
    return ip, mac, found

def setOccupied(ip, vmid, node):
    with open("addresses.json", "r") as f:
        data = json.load(f)

    found = False
    for i in range(len(data["addresses"])):
        if (data["addresses"][i]["ip"] == ip):
            data["addresses"][i]["vmid"] = vmid 
            data["addresses"][i]["node"] = node
            found = True
            break

    if found:
        with open("addresses.json", "w") as f:
            json.dump(data, f, indent=4)

    return found

def setAddressesFreeAndUpload(ip: str):
    with open("addresses.json", "r") as f:
        data = json.load(f)
    vmid, node = None, None
    found = False
    for item in data["addresses"]:
        if item["ip"] == ip:
            vmid, node = item['vmid'], item['node']
            item['vmid'], item['node'] = None, None
            found = True
            break
    if found:
        with open("addresses.json", "w") as f:
            json.dump(data, f, indent=4)
    return vmid, node, found



async def waitTask(node, upid, timeout=300, interval=1):
    start = asyncio.get_event_loop().time()
    
    while True:
        if asyncio.get_event_loop().time() - start > timeout:
            raise TimeoutError(f"Task {upid} exceeded {timeout} seconds")
        
        task_status = proxmox.nodes(node).tasks(upid).status.get()
        status = task_status["status"]
        
        if status == "stopped":
            exitcode = task_status.get("exitstatus")
            if exitcode != "OK":
                raise RuntimeError(f"Task {upid} failed: {exitcode}")
            return
        
        await asyncio.sleep(interval)

