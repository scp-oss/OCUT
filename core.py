"""
Core logic for the EFI updater web tool - no network calls are made at
import time, everything is a plain function so it can be unit tested
without hitting GitHub. Pure stdlib (json/urllib/zipfile/plistlib/hashlib),
deliberately no third-party dependencies.

This runs on the machine that actually has internet access and the real
EFI folder (your Mac) - not in a sandbox with no GitHub access.
"""
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

API_ROOT = "https://api.github.com/repos"
UA = "Mozilla/5.0 (compatible; OCUT/1.0)"
STATE_FILENAME = ".efi_updater_state.json"
COMPONENTS_FILENAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "components.json")

DEFAULT_COMPONENTS = [
    {"name": "Lilu", "repo": "acidanthera/Lilu", "kexts": ["Lilu.kext"]},
    {"name": "WhateverGreen", "repo": "acidanthera/WhateverGreen", "kexts": ["WhateverGreen.kext"]},
    {"name": "VirtualSMC", "repo": "acidanthera/VirtualSMC",
     "kexts": ["VirtualSMC.kext", "SMCProcessor.kext", "SMCSuperIO.kext"]},
    {"name": "NVMeFix", "repo": "acidanthera/NVMeFix", "kexts": ["NVMeFix.kext"]},
    {"name": "RestrictEvents", "repo": "acidanthera/RestrictEvents", "kexts": ["RestrictEvents.kext"]},
    {"name": "BrcmPatchRAM", "repo": "acidanthera/BrcmPatchRAM", "kexts": ["BlueToolFixup.kext"]},
    {"name": "USBToolBox", "repo": "USBToolBox/kext", "kexts": ["USBToolBox.kext"]},
    {"name": "IntelMausi", "repo": "acidanthera/IntelMausi", "kexts": ["IntelMausi.kext"]},
]
OPENCORE_REPO = "acidanthera/OpenCorePkg"

# Curated kext picker for "+ Добавить" - parsed directly (regex over the raw
# source, not executed) from lzhoang2801/OpCore-Simplify's own
# Scripts/datasets/kext_data.py, per direct request to reuse that project's
# list rather than making users type an owner/repo blind. Only the 76
# entries that ship a real github_repo were kept (OpCore-Simplify has ~12
# more - old Apple-signed system kexts and similar - that point at
# nightly.link/direct-archive URLs instead of a repo with releases, which
# doesn't fit this tool's update model at all). The catalog's own "name" is
# the actual kext product name, not just the project/repo name - verified
# against BrcmPatchRAM's entry ("BlueToolFixup", not "BrcmPatchRAM") before
# trusting `name + ".kext"` as the bundle filename for every entry; this
# project already did the "what's the real kext called" homework that bit
# us with the IntelMausiEthernet/IntelMausi mixup, so entries picked from
# here don't need a download-and-peek step the way a raw manual add would.
KEXT_CATALOG = [
    {"name": "Lilu", "description": "For arbitrary kext, library, and program patching", "category": "Required", "owner": "acidanthera", "repo": "Lilu"},
    {"name": "VirtualSMC", "description": "Advanced Apple SMC emulator in the kernel", "category": "Required", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "SMCBatteryManager", "description": "Manages, monitors, and reports on battery status", "category": "VirtualSMC Plugins", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "SMCDellSensors", "description": "Enables fan monitoring and control on Dell computers", "category": "VirtualSMC Plugins", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "SMCLightSensor", "description": "Allows system utilize ambient light sensor device", "category": "VirtualSMC Plugins", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "SMCProcessor", "description": "Manages Intel CPU temperature sensors", "category": "VirtualSMC Plugins", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "SMCRadeonSensors", "description": "Provides temperature readings for AMD GPUs", "category": "VirtualSMC Plugins", "owner": "ChefKissInc", "repo": "SMCRadeonSensors"},
    {"name": "SMCSuperIO", "description": "Monitoring hardware sensors and controlling fan speeds", "category": "VirtualSMC Plugins", "owner": "acidanthera", "repo": "VirtualSMC"},
    {"name": "NootRX", "description": "The rDNA 2 dGPU support patch kext", "category": "Graphics", "owner": "ChefKissInc", "repo": "NootRX"},
    {"name": "NootedRed", "description": "The AMD Vega iGPU support kext", "category": "Graphics", "owner": "ChefKissInc", "repo": "NootedRed"},
    {"name": "WhateverGreen", "description": "Various patches necessary for GPUs are pre-supported", "category": "Graphics", "owner": "acidanthera", "repo": "WhateverGreen"},
    {"name": "AppleALC", "description": "Native macOS HD audio for not officially supported codecs", "category": "Audio", "owner": "acidanthera", "repo": "AppleALC"},
    {"name": "AirportBrcmFixup", "description": "Patches required for non-native Broadcom Wi-Fi cards", "category": "Wi-Fi", "owner": "acidanthera", "repo": "AirportBrcmFixup"},
    {"name": "AirportItlwm", "description": "Intel Wi-Fi drivers support the native macOS Wi-Fi interface", "category": "Wi-Fi", "owner": "DexterSLamb", "repo": "itlwm"},
    {"name": "Feixiao", "description": "Realtek WLAN (rtw88) driver for macOS", "category": "Wi-Fi", "owner": "thegwchr", "repo": "Feixiao"},
    {"name": "itlwm", "description": "Intel Wi-Fi drivers. Spoofs as Ethernet and connects to Wi-Fi via Heliport", "category": "Wi-Fi", "owner": "DexterSLamb", "repo": "itlwm"},
    {"name": "Ath3kBT", "description": "Uploads firmware to enable Atheros Bluetooth support", "category": "Bluetooth", "owner": "zxystd", "repo": "AthBluetoothFirmware"},
    {"name": "Ath3kBTInjector", "description": "Uploads firmware to enable Atheros Bluetooth support", "category": "Bluetooth", "owner": "zxystd", "repo": "AthBluetoothFirmware"},
    {"name": "BlueToolFixup", "description": "Patches Bluetooth stack to support third-party cards", "category": "Bluetooth", "owner": "acidanthera", "repo": "BrcmPatchRAM"},
    {"name": "BrcmBluetoothInjector", "description": "Enables the Broadcom Bluetooth on/off switch on older versions", "category": "Bluetooth", "owner": "acidanthera", "repo": "BrcmPatchRAM"},
    {"name": "BrcmFirmwareData", "description": "Applies PatchRAM updates for Broadcom RAMUSB based devices", "category": "Bluetooth", "owner": "acidanthera", "repo": "BrcmPatchRAM"},
    {"name": "BrcmPatchRAM2", "description": "Applies PatchRAM updates for Broadcom RAMUSB based devices", "category": "Bluetooth", "owner": "acidanthera", "repo": "BrcmPatchRAM"},
    {"name": "BrcmPatchRAM3", "description": "Applies PatchRAM updates for Broadcom RAMUSB based devices", "category": "Bluetooth", "owner": "acidanthera", "repo": "BrcmPatchRAM"},
    {"name": "IntelBluetoothFirmware", "description": "Uploads firmware to enable Intel Bluetooth support", "category": "Bluetooth", "owner": "lshbluesky", "repo": "IntelBluetoothFirmware"},
    {"name": "IntelBTPatcher", "description": "Fixes Intel Bluetooth bugs for better connectivity", "category": "Bluetooth", "owner": "lshbluesky", "repo": "IntelBluetoothFirmware"},
    {"name": "IntelBluetoothInjector", "description": "Enables the Intel Bluetooth on/off switch on older versions", "category": "Bluetooth", "owner": "lshbluesky", "repo": "IntelBluetoothFirmware"},
    {"name": "RealtekBluetoothFirmware", "description": "Uploads firmware to enable Realtek Bluetooth support", "category": "Bluetooth", "owner": "thegwchr", "repo": "RealtekBluetoothFirmware"},
    {"name": "AppleIGB", "description": "Provides support for Intel's IGB Ethernet controllers", "category": "Ethernet", "owner": "donatengit", "repo": "AppleIGB"},
    {"name": "AppleIGC", "description": "Provides support for Intel 2.5G Ethernet(i225/i226)", "category": "Ethernet", "owner": "SongXiaoXi", "repo": "AppleIGC"},
    {"name": "AtherosE2200Ethernet", "description": "Provides support for Atheros E2200 family", "category": "Ethernet", "owner": "Mieze", "repo": "AtherosE2200Ethernet"},
    {"name": "HoRNDIS", "description": "Use the USB tethering mode of the Android phone to access the Internet", "category": "Ethernet", "owner": "TomHeaven", "repo": "HoRNDIS"},
    {"name": "IntelLucy", "description": "Provides support for Intel X500 family", "category": "Ethernet", "owner": "Mieze", "repo": "IntelLucy"},
    {"name": "IntelMausi", "description": "Intel Ethernet LAN driver for macOS (актуальный форк, продолжает IntelMausiEthernet)", "category": "Ethernet", "owner": "acidanthera", "repo": "IntelMausi"},
    {"name": "IntelMausiEthernet", "description": "Intel Ethernet LAN driver for macOS (оригинал Mieze, с 3.0.0 без активности - см. IntelMausi выше)", "category": "Ethernet", "owner": "CloverHackyColor", "repo": "IntelMausiEthernet"},
    {"name": "LucyRTL8125Ethernet", "description": "Provides support for Realtek RTL8125 family", "category": "Ethernet", "owner": "Mieze", "repo": "LucyRTL8125Ethernet"},
    {"name": "NullEthernet", "description": "Creates a Null Ethernet when no supported network hardware is present", "category": "Ethernet", "owner": "RehabMan", "repo": "os-x-null-ethernet"},
    {"name": "RealtekRTL8100", "description": "Provides support for Realtek RTL8100 family", "category": "Ethernet", "owner": "Mieze", "repo": "RealtekRTL8100"},
    {"name": "RealtekRTL8111", "description": "Provides support for Realtek RTL8111/8168 family", "category": "Ethernet", "owner": "Mieze", "repo": "RTL8111_driver_for_OS_X"},
    {"name": "RTL812xLucy", "description": "A new macOS driver for the Realtek RTL812x family", "category": "Ethernet", "owner": "Mieze", "repo": "RTL812xLucy"},
    {"name": "GenericUSBXHCI", "description": "Fixes USB 3.0 issues found on some Ryzen APU-based", "category": "USB", "owner": "RattletraPM", "repo": "GUX-RyzenXHCIFix"},
    {"name": "USBToolBox", "description": "Flexible USB mapping", "category": "USB", "owner": "USBToolBox", "repo": "kext"},
    {"name": "UTBDefault", "description": "Enables all USB ports (assumes no port limit)", "category": "USB", "owner": "USBToolBox", "repo": "kext"},
    {"name": "XHCI-unsupported", "description": "Enables USB 3.0 support for unsupported xHCI controllers", "category": "USB", "owner": "daliansky", "repo": "OS-X-USB-Inject-All"},
    {"name": "AlpsHID", "description": "Brings native multitouch support to the Alps I2C touchpad", "category": "Input", "owner": "blankmac", "repo": "AlpsHID"},
    {"name": "VoodooInput", "description": "Provides Magic Trackpad 2 software emulation for arbitrary input sources", "category": "Input", "owner": "acidanthera", "repo": "VoodooInput"},
    {"name": "VoodooPS2Controller", "description": "Provides support for PS/2 keyboards, trackpads, and mouse", "category": "Input", "owner": "acidanthera", "repo": "VoodooPS2"},
    {"name": "VoodooRMI", "description": "Synaptic Trackpad kext over SMBus/I2C", "category": "Input", "owner": "VoodooSMBus", "repo": "VoodooRMI"},
    {"name": "VoodooSMBus", "description": "i2c-i801 + ELAN SMBus Touchpad kext", "category": "Input", "owner": "VoodooSMBus", "repo": "VoodooSMBus"},
    {"name": "VoodooI2C", "description": "Intel I2C controller and slave device drivers", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "VoodooI2CAtmelMXT", "description": "A satellite kext for Atmel MXT I2C touchscreen", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "VoodooI2CELAN", "description": "A satellite kext for ELAN I2C touchpads", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "VoodooI2CFTE", "description": "A satellite kext for FTE based touchpads", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "VoodooI2CHID", "description": "A satellite kext for HID I2C or ELAN1200+ input devices", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "VoodooI2CSynaptics", "description": "A satellite kext for Synaptics I2C touchpads", "category": "Input", "owner": "VoodooI2C", "repo": "VoodooI2C"},
    {"name": "AsusSMC", "description": "Supports ALS, keyboard backlight, and Fn keys on ASUS laptops", "category": "Brand Specific", "owner": "hieplpvip", "repo": "AsusSMC"},
    {"name": "BigSurface", "description": "A fully intergrated kext for all Surface related hardwares", "category": "Brand Specific", "owner": "Xiashangning", "repo": "BigSurface"},
    {"name": "YogaSMC", "description": "Enables support for syncing SMC keys, controlling sensors and managing vendor-specific features", "category": "Brand Specific", "owner": "zhen-zen", "repo": "YogaSMC"},
    {"name": "NVMeFix", "description": "Addresses compatibility and performance issues with NVMe SSDs", "category": "Storage", "owner": "acidanthera", "repo": "NVMeFix"},
    {"name": "PC711Probe", "description": "A probe kext for SK Hynix PC711 NVMe SSDs", "category": "Storage", "owner": "hrx114514x", "repo": "PC711Probe"},
    {"name": "PC711ProbeForce", "description": "Applies the MSI-X compatibility path to all NVMe controllers", "category": "Storage", "owner": "hrx114514x", "repo": "PC711Probe"},
    {"name": "RealtekCardReader", "description": "Realtek PCIe/USB-based SD card reader driver", "category": "Card Reader", "owner": "0xFireWolf", "repo": "RealtekCardReader"},
    {"name": "RealtekCardReaderFriend", "description": "Makes System Information recognize your Realtek card reader", "category": "Card Reader", "owner": "0xFireWolf", "repo": "RealtekCardReaderFriend"},
    {"name": "Sinetek-rtsx", "description": "Realtek PCIe-based SD card reader driver", "category": "Card Reader", "owner": "cholonam", "repo": "Sinetek-rtsx"},
    {"name": "AmdTscSync", "description": "A modified version of VoodooTSCSync for AMD CPUs", "category": "TSC Synchronization", "owner": "naveenkrdy", "repo": "AmdTscSync"},
    {"name": "VoodooTSCSync", "description": "A kernel extension which will synchronize the TSC on Intel CPUs", "category": "TSC Synchronization", "owner": "RehabMan", "repo": "VoodooTSCSync"},
    {"name": "CpuTscSync", "description": "Lilu plugin for TSC sync and disabling xcpm_urgency on Intel CPUs", "category": "TSC Synchronization", "owner": "acidanthera", "repo": "CpuTscSync"},
    {"name": "ForgedInvariant", "description": "The plug & play kext for syncing the TSC on AMD & Intel", "category": "TSC Synchronization", "owner": "ChefKissInc", "repo": "ForgedInvariant"},
    {"name": "BrightnessKeys", "description": "Handler for brightness keys without DSDT patches", "category": "Extras", "owner": "acidanthera", "repo": "BrightnessKeys"},
    {"name": "CPUFriend", "description": "Dynamic power management data injection (requires CPUFriendDataProvider)", "category": "Extras", "owner": "acidanthera", "repo": "CPUFriend"},
    {"name": "CpuTopologyRebuild", "description": "Optimizes the core configuration of Intel Alder Lake CPUs+", "category": "Extras", "owner": "b00t0x", "repo": "CpuTopologyRebuild"},
    {"name": "CryptexFixup", "description": "Various patches to install Rosetta cryptex", "category": "Extras", "owner": "acidanthera", "repo": "CryptexFixup"},
    {"name": "ECEnabler", "description": "Allows reading Embedded Controller fields over 1 byte long", "category": "Extras", "owner": "1Revenger1", "repo": "ECEnabler"},
    {"name": "FeatureUnlock", "description": "Enable additional features on unsupported hardware", "category": "Extras", "owner": "acidanthera", "repo": "FeatureUnlock"},
    {"name": "HibernationFixup", "description": "Fixes hibernation compatibility issues", "category": "Extras", "owner": "acidanthera", "repo": "HibernationFixup"},
    {"name": "NoTouchID", "description": "Avoid lag in authentication dialogs for board IDs with Touch ID sensors", "category": "Extras", "owner": "al3xtjames", "repo": "NoTouchID"},
    {"name": "RestrictEvents", "description": "Blocking unwanted processes and unlocking features", "category": "Extras", "owner": "acidanthera", "repo": "RestrictEvents"},
    {"name": "RTCMemoryFixup", "description": "Emulate some offsets in your CMOS (RTC) memory", "category": "Extras", "owner": "acidanthera", "repo": "RTCMemoryFixup"},
]

# Dortania's build-repo (https://dortania.github.io/builds/) rebuilds
# acidanthera-ecosystem projects from upstream `master` on every commit -
# ahead of official tagged releases, and unlike hitting api.github.com per
# project this is a single raw file covering every tracked project at once
# (no REST rate limit, since it's not a github.com API call). Made the
# primary source per direct request - resolve_component_build() falls back
# to the component's own GitHub releases only when Dortania doesn't track
# it (confirmed absent for USBToolBox) or when fetching the manifest
# itself fails.
#
# IntelMausiEthernet -> IntelMausi (2026-09): Mieze/IntelMausiEthernet's
# last real release is 3.0.0 with no activity since - acidanthera forked
# it as IntelMausi (own version numbering from 1.0.0, unrelated to
# Mieze's 3.x) and is the one Dortania actually tracks. Verified by
# downloading the real Dortania build and inspecting the zip directly
# (not just assuming from the project name): the bundle really is
# IntelMausi.kext, not IntelMausiEthernet.kext - config.plist's
# Kernel->Add BundlePath/ExecutablePath in opencore-h410sb were updated
# to match in the same pass, this isn't just a source-URL swap.
DORTANIA_MANIFEST_URL = "https://raw.githubusercontent.com/dortania/build-repo/builds/latest.json"


def load_components():
    """Tracked components live in components.json next to this file, not
    hardcoded - so adding/removing one from the UI doesn't need a code
    change. Falls back to DEFAULT_COMPONENTS (and writes it out) on first
    run or if the file is missing/corrupt."""
    if os.path.isfile(COMPONENTS_FILENAME):
        try:
            with open(COMPONENTS_FILENAME) as f:
                return json.load(f)
        except Exception:
            pass
    save_components(DEFAULT_COMPONENTS)
    return list(DEFAULT_COMPONENTS)


def save_components(components):
    with open(COMPONENTS_FILENAME, "w") as f:
        json.dump(components, f, indent=2)


def add_component(repo, kexts, name=None):
    """`name` is optional - the tracked component's display name is just
    the repo's own last path segment unless the caller overrides it
    (nothing in the UI does anymore; a typed-name field was removed as
    redundant per direct request, since the repo already implies it)."""
    if not name:
        name = repo.rstrip("/").split("/")[-1]
    components = load_components()
    if any(c["name"] == name for c in components):
        raise RuntimeError(f"'{name}' уже отслеживается")
    components.append({"name": name, "repo": repo, "kexts": kexts})
    save_components(components)
    return components


def remove_component(name):
    components = load_components()
    filtered = [c for c in components if c["name"] != name]
    if len(filtered) == len(components):
        raise RuntimeError(f"'{name}' не найден среди отслеживаемых")
    save_components(filtered)
    return filtered


def get_kext_catalog():
    """Curated picker data for the '+ Добавить' -> 'Из каталога' tab - see
    KEXT_CATALOG's own comment for provenance. Returned as-is; grouping by
    category and any search filtering happens client-side, this is just
    the raw list."""
    return KEXT_CATALOG


def add_kexts_from_catalog(names):
    """Add one or more catalog picks as tracked components, grouped by
    their real owner/repo - several catalog entries can share one repo
    (e.g. every VirtualSMC plugin, or BrcmPatchRAM's five kexts), and this
    merges into an already-tracked component for that repo instead of
    erroring, so re-picking something already tracked is a harmless
    no-op rather than a duplicate-name failure. A newly created
    component's name is the repo's own name (last path segment) - same
    auto-derivation as the manual add-by-repo path, there's no separate
    user-typed name here either."""
    catalog_by_name = {k["name"]: k for k in KEXT_CATALOG}
    unknown = [n for n in names if n not in catalog_by_name]
    if unknown:
        raise RuntimeError(f"неизвестные записи каталога: {', '.join(unknown)}")

    components = load_components()
    by_repo = {c["repo"]: c for c in components}
    added = []
    for n in names:
        entry = catalog_by_name[n]
        repo = f"{entry['owner']}/{entry['repo']}"
        bundle = f"{entry['name']}.kext"
        comp = by_repo.get(repo)
        if comp is None:
            comp = {"name": entry["repo"], "repo": repo, "kexts": []}
            components.append(comp)
            by_repo[repo] = comp
        if bundle not in comp["kexts"]:
            comp["kexts"].append(bundle)
            added.append(bundle)
    save_components(components)
    return {"components": components, "added": added}


def list_kexts_in_folder(folder):
    """.kext bundles directly inside `folder` (one level, not recursive) -
    backs the '+ Добавить' -> 'С диска' flow: point the native folder
    picker at wherever a kext was downloaded/built/AirDropped to, and pick
    which bundle(s) inside it to copy into Kexts/."""
    if not os.path.isdir(folder):
        raise RuntimeError(f"'{folder}' не папка")
    found = []
    for name in sorted(os.listdir(folder)):
        if is_junk_metadata_name(name):
            continue
        if name.endswith(".kext") and os.path.isdir(os.path.join(folder, name)):
            found.append(name)
    return found


def import_kext_from_folder(root, source_folder, bundle_name):
    """Copy an already-on-disk .kext bundle (not downloaded by OCUT itself)
    into this EFI's Kexts/ folder. Deliberately does not touch
    config.plist or components.json - wiring it into Kernel->Add is the
    same separate, explicit add_kext_to_config() step every other
    present-but-unwired kext already goes through, so an imported kext
    shows up exactly like one dropped in by hand."""
    if is_junk_metadata_name(bundle_name) or not bundle_name.endswith(".kext"):
        raise RuntimeError(f"'{bundle_name}' не похоже на .kext")
    src = os.path.join(source_folder, bundle_name)
    if not os.path.isdir(src):
        raise RuntimeError(f"'{bundle_name}' не найден в '{source_folder}'")
    kexts_dir = os.path.join(root, "Kexts")
    if not os.path.isdir(kexts_dir):
        raise RuntimeError(f"'{root}' doesn't look like an EFI/OC checkout (no Kexts/ found)")
    dst = os.path.join(kexts_dir, bundle_name)
    if os.path.exists(dst):
        raise RuntimeError(f"{bundle_name} уже есть в Kexts/")
    shutil.copytree(src, dst)
    return {"bundle": bundle_name, "copied_to": dst}

# Per-board artifacts that must never be silently overwritten by an
# upstream "generic" version - they're generated/curated specifically for
# this machine, not a thing with an upstream release to pull.
MANUAL_ONLY_KEXTS = {"UTBDefault.kext", "XHCI-unsupported.kext"}


# ---------------------------------------------------------------- GitHub --

def _gh_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def resolve_release(repo, channel):
    """channel: 'stable' or 'prerelease'. Returns (tag, assets, html_url)."""
    if channel == "stable":
        data = _gh_get_json(f"{API_ROOT}/{repo}/releases/latest")
    else:
        releases = _gh_get_json(f"{API_ROOT}/{repo}/releases?per_page=5")
        if not releases:
            raise RuntimeError(f"{repo} has no releases at all")
        data = releases[0]  # GitHub lists newest first, prereleases included
    tag = data["tag_name"].lstrip("v")
    assets = [(a["name"], a["browser_download_url"]) for a in data.get("assets", [])]
    return tag, assets, data.get("html_url", "")


def fetch_dortania_manifest():
    req = urllib.request.Request(DORTANIA_MANIFEST_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def dortania_lookup(manifest, project_name):
    """None if this project isn't tracked by Dortania at all, or the
    manifest doesn't have the expected shape for it - caller should treat
    that exactly like "no Dortania data" and fall back to GitHub, not
    raise. Real schema, verified against the live manifest:
    manifest["Lilu"]["versions"][0] == {"version": "1.7.3",
    "links": {"release": "<direct .zip url>", "debug": "..."},
    "hashes": {"release": {"sha256": "..."}, ...},
    "release": {"url": "<build-repo release page>", "id": ...}, ...}."""
    entry = manifest.get(project_name)
    if not entry or not entry.get("versions"):
        return None
    latest = entry["versions"][0]
    try:
        return {
            "version": latest["version"],
            "url": latest["links"]["release"],
            "sha256": latest["hashes"]["release"]["sha256"],
            "html_url": latest["release"]["url"],
        }
    except KeyError:
        return None


def resolve_component_build(component, channel, manifest):
    """Single entry point used by both check_updates() and the actual
    apply_*() functions, so "what version/URL did we check" and "what did
    we download" can never silently disagree. Tries Dortania first
    (manifest may be None if fetching it failed - that's a normal,
    already-logged fallback trigger, not an error to raise here), then the
    component's own GitHub releases on the given channel."""
    dortania_name = component.get("dortania_name", component["name"])
    if manifest is not None:
        hit = dortania_lookup(manifest, dortania_name)
        if hit:
            return {
                "version": hit["version"], "asset_url": hit["url"], "sha256": hit["sha256"],
                "source": "dortania", "html_url": hit["html_url"],
            }
    tag, assets, url = resolve_release(component["repo"], channel)
    asset_name, asset_url = pick_asset(assets)
    return {"version": tag, "asset_url": asset_url, "sha256": None, "source": "github", "html_url": url}


def pick_asset(assets):
    release_named = [a for a in assets if "release" in a[0].lower() and a[0].lower().endswith(".zip")]
    if release_named:
        return release_named[0]
    plain_zips = [a for a in assets if a[0].lower().endswith(".zip")
                  and "debug" not in a[0].lower() and "source code" not in a[0].lower()]
    if plain_zips:
        return plain_zips[0]
    raise RuntimeError(f"no usable .zip asset among: {[a[0] for a in assets]}")


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)


def repo_default_branch(repo):
    return _gh_get_json(f"{API_ROOT}/{repo}").get("default_branch", "master")


def download_repo_archive(repo, dest_zip, ref=None):
    """Whole-repo snapshot (for theme repos, which aren't released as
    versioned zips the way kexts are - just 'give me Resources/ as it is
    on the default branch')."""
    ref = ref or repo_default_branch(repo)
    url = f"https://api.github.com/repos/{repo}/zipball/{ref}"
    download(url, dest_zip)


# ----------------------------------------------------------- backups ----

def _version_slug(version):
    return re.sub(r"[^A-Za-z0-9.]+", "_", version) if version else "unknown"


def backup_oc_folder_zip(root):
    """One full zip snapshot of the whole OC folder, taken right before
    ANY update button's action runs - stored as a SIBLING of the OC folder
    (not inside it, so it never gets swept up as "just another file in
    Kexts/" by a future scan, and doesn't grow the folder OpenCore itself
    boots from). Restoring is just unzipping it back over the parent
    directory - the zip's internal paths already start with the OC
    folder's own name.

    Filename: oc-<version>-<date>-<n>.zip - version is whatever OpenCore
    reports as currently running (NVRAM, see read_live_opencore_version())
    since that's the most meaningful single label for a snapshot of the
    ENTIRE folder, falling back to the last version OCUT itself applied,
    then "unknown" - <n> avoids collisions if this fires more than once
    the same day (e.g. updating several kexts back to back).
    """
    root = os.path.abspath(root)
    parent_dir = os.path.dirname(root)
    oc_dirname = os.path.basename(root)

    state = load_state(root)
    version = read_live_opencore_version() or state.get("opencore", {}).get("version") or "unknown"
    date = time.strftime("%Y%m%d")

    n = 1
    while True:
        dest = os.path.join(parent_dir, f"oc-{_version_slug(version)}-{date}-{n}.zip")
        if not os.path.exists(dest):
            break
        n += 1

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if is_junk_metadata_name(fname):
                    continue
                full = os.path.join(dirpath, fname)
                arcname = os.path.join(oc_dirname, os.path.relpath(full, root))
                z.write(full, arcname)

    return dest


# --------------------------------------------------------- filesystem ----

def find_in_tree(root, name):
    for dirpath, dirnames, _ in os.walk(root):
        if name in dirnames:
            return os.path.join(dirpath, name)
    return None


def find_dir_named(root, name):
    """Like find_in_tree but also matches a directory whose name merely
    ends with the target (zipball archives prefix the repo dir with a
    commit hash, e.g. 'acidanthera-OcBinaryData-abcdef')."""
    exact = find_in_tree(root, name)
    if exact:
        return exact
    for dirpath, dirnames, _ in os.walk(root):
        for d in dirnames:
            if d == name:
                return os.path.join(dirpath, d)
    return None


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_junk_metadata_name(name):
    """AppleDouble sidecar files (macOS writes '._foo' next to 'foo' on
    filesystems without native resource-fork/xattr support, like the FAT32
    EFI system partition every OpenCore install actually uses) and Finder's
    .DS_Store - never real driver/kext files, but '._Foo.kext' still passes
    a naive `.endswith('.kext')` check, so this needs checking everywhere
    directory listings are filtered, not just here."""
    return name == ".DS_Store" or name.startswith("._")


def local_kext_version(kext_path):
    info = os.path.join(kext_path, "Contents", "Info.plist")
    if not os.path.isfile(info):
        return None
    try:
        with open(info, "rb") as f:
            d = plistlib.load(f)
        return d.get("CFBundleShortVersionString") or d.get("CFBundleVersion")
    except Exception:
        return None


def load_state(root):
    path = os.path.join(root, STATE_FILENAME)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(root, state):
    path = os.path.join(root, STATE_FILENAME)
    with open(path, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


# --------------------------------------------------------- Kernel->Add ---

def _config_path(root):
    return os.path.join(root, "config.plist")


def _load_config(root):
    with open(_config_path(root), "rb") as f:
        return plistlib.load(f)


def _save_config(root, config):
    with open(_config_path(root), "wb") as f:
        plistlib.dump(config, f)


def _find_kernel_add_index(entries, bundle):
    for i, entry in enumerate(entries):
        if entry.get("BundlePath") == bundle:
            return i
    return -1


def kext_config_status(root, bundle):
    """{"wired": False} if there's no Kernel->Add entry for this bundle at
    all (kext sitting in Kexts/ but never referenced - OpenCore will never
    load it); otherwise {"wired": True, "enabled": bool}."""
    config = _load_config(root)
    entries = config.get("Kernel", {}).get("Add", [])
    idx = _find_kernel_add_index(entries, bundle)
    if idx == -1:
        return {"wired": False, "enabled": None}
    return {"wired": True, "enabled": bool(entries[idx].get("Enabled", False))}


def set_kext_enabled(root, bundle, enabled):
    config = _load_config(root)
    entries = config.setdefault("Kernel", {}).setdefault("Add", [])
    idx = _find_kernel_add_index(entries, bundle)
    if idx == -1:
        raise RuntimeError(f"{bundle} не подключён в Kernel->Add - сначала добавьте запись")
    entries[idx]["Enabled"] = bool(enabled)
    _save_config(root, config)
    return {"bundle": bundle, "enabled": bool(enabled)}


def _guess_executable_path(kexts_dir, bundle):
    """Most kexts have a Mach-O binary at Contents/MacOS/<name-without-.kext>
    (matches every real entry already in this repo's own config.plist);
    a codeless/property-only kext (UTBDefault.kext, XHCI-unsupported.kext)
    has none, and OpenCore's own convention is an empty string there."""
    stem = bundle[:-len(".kext")] if bundle.endswith(".kext") else bundle
    candidate = os.path.join(kexts_dir, bundle, "Contents", "MacOS", stem)
    return f"Contents/MacOS/{stem}" if os.path.isfile(candidate) else ""


def add_kext_to_config(root, bundle, arch="x86_64", enabled=True):
    kexts_dir = os.path.join(root, "Kexts")
    if not os.path.isdir(os.path.join(kexts_dir, bundle)):
        raise RuntimeError(f"{bundle} не найден в Kexts/ - сначала скачайте/скопируйте сам кекст")

    config = _load_config(root)
    entries = config.setdefault("Kernel", {}).setdefault("Add", [])
    if _find_kernel_add_index(entries, bundle) != -1:
        raise RuntimeError(f"{bundle} уже есть в Kernel->Add")

    entries.append({
        "Arch": arch,
        "BundlePath": bundle,
        "Comment": "",
        "Enabled": bool(enabled),
        "ExecutablePath": _guess_executable_path(kexts_dir, bundle),
        "MaxKernel": "",
        "MinKernel": "",
        "PlistPath": "Contents/Info.plist",
    })
    _save_config(root, config)
    return {"bundle": bundle, "added": True}


def remove_kext_from_config(root, bundle):
    config = _load_config(root)
    entries = config.get("Kernel", {}).get("Add", [])
    idx = _find_kernel_add_index(entries, bundle)
    if idx == -1:
        raise RuntimeError(f"{bundle} не найден в Kernel->Add")
    del entries[idx]
    _save_config(root, config)
    return {"bundle": bundle, "removed": True}


def remove_kexts_from_config_bulk(root, bundles):
    """Bulk version for the table's checkbox multi-select + 'Удалить' ->
    'Подтвердить удаление' flow - tolerant of an already-unwired bundle in
    the selection (skipped, not an error), since the row checkbox is a
    plain row-selector and doesn't restrict selection to only-wired
    rows."""
    removed, skipped = [], []
    for bundle in bundles:
        try:
            remove_kext_from_config(root, bundle)
            removed.append(bundle)
        except RuntimeError:
            skipped.append(bundle)
    return {"removed": removed, "skipped": skipped}


# ------------------------------------------------------------ UEFI->Drivers

def _find_uefi_driver_index(entries, filename):
    for i, entry in enumerate(entries):
        if entry.get("Path") == filename:
            return i
    return -1


def driver_config_status(root, filename):
    """Same shape as kext_config_status() - {"wired": False} if there's no
    UEFI->Drivers entry for this file at all, otherwise {"wired": True,
    "enabled": bool}. Real entry shape confirmed against this repo's own
    config.plist: {"Arguments": "", "Comment": "", "Enabled": bool,
    "LoadEarly": bool, "Path": "<file>.efi"} - matched on Path, the
    Drivers/*.efi equivalent of a kext's BundlePath."""
    config = _load_config(root)
    entries = config.get("UEFI", {}).get("Drivers", [])
    idx = _find_uefi_driver_index(entries, filename)
    if idx == -1:
        return {"wired": False, "enabled": None}
    return {"wired": True, "enabled": bool(entries[idx].get("Enabled", False))}


def set_driver_enabled(root, filename, enabled):
    config = _load_config(root)
    entries = config.setdefault("UEFI", {}).setdefault("Drivers", [])
    idx = _find_uefi_driver_index(entries, filename)
    if idx == -1:
        raise RuntimeError(f"{filename} не подключён в UEFI->Drivers - сначала добавьте запись")
    entries[idx]["Enabled"] = bool(enabled)
    _save_config(root, config)
    return {"file": filename, "enabled": bool(enabled)}


def add_driver_to_config(root, filename, load_early=False, enabled=True):
    drivers_dir = os.path.join(root, "Drivers")
    if not os.path.isfile(os.path.join(drivers_dir, filename)):
        raise RuntimeError(f"{filename} не найден в Drivers/ - сначала скачайте/скопируйте сам файл")

    config = _load_config(root)
    entries = config.setdefault("UEFI", {}).setdefault("Drivers", [])
    if _find_uefi_driver_index(entries, filename) != -1:
        raise RuntimeError(f"{filename} уже есть в UEFI->Drivers")

    entries.append({
        "Arguments": "",
        "Comment": "",
        "Enabled": bool(enabled),
        "LoadEarly": bool(load_early),
        "Path": filename,
    })
    _save_config(root, config)
    return {"file": filename, "added": True}


def remove_driver_from_config(root, filename):
    config = _load_config(root)
    entries = config.get("UEFI", {}).get("Drivers", [])
    idx = _find_uefi_driver_index(entries, filename)
    if idx == -1:
        raise RuntimeError(f"{filename} не найден в UEFI->Drivers")
    del entries[idx]
    _save_config(root, config)
    return {"file": filename, "removed": True}


def remove_drivers_from_config_bulk(root, files):
    """Bulk version for the drivers table's checkbox multi-select +
    'Удалить' -> 'Подтвердить удаление' flow - same tolerant-of-unwired
    semantics as remove_kexts_from_config_bulk()."""
    removed, skipped = [], []
    for filename in files:
        try:
            remove_driver_from_config(root, filename)
            removed.append(filename)
        except RuntimeError:
            skipped.append(filename)
    return {"removed": removed, "skipped": skipped}


def fetch_driver_from_opencore(root, filename, channel, log):
    """Pull just ONE driver file out of the current OpenCorePkg build's
    Drivers/ folder - for adding a stock driver (e.g. OpenHfsPlus.efi)
    that isn't installed yet, without touching OpenCore.efi or any other
    driver already present. Same backup-first + Dortania-first + sha256
    verification path as apply_opencore(), just narrowed to one file
    afterwards."""
    backup_path = backup_oc_folder_zip(root)
    log.append(f"[Drivers] backup -> {backup_path}")

    manifest = None
    try:
        manifest = fetch_dortania_manifest()
    except Exception as e:
        log.append(f"[Drivers] Dortania manifest unavailable ({e}), falling back to GitHub releases")

    build = resolve_component_build({"name": "OpenCorePkg", "repo": OPENCORE_REPO}, channel, manifest)
    asset_name = os.path.basename(build["asset_url"])
    log.append(f"[Drivers] source={build['source']} {asset_name} -> {build['version']}")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, asset_name)
        download(build["asset_url"], zip_path)
        if build["sha256"]:
            actual = sha256_of(zip_path)
            if actual != build["sha256"]:
                raise RuntimeError(f"sha256 mismatch for {asset_name}: expected {build['sha256']}, got {actual}")
            log.append("[Drivers] sha256 verified against Dortania manifest")
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)

        oc_dir = None
        for dirpath, _, filenames in os.walk(extract_dir):
            if "OpenCore.efi" in filenames and "X64" in dirpath.split(os.sep):
                oc_dir = dirpath
                break
        if not oc_dir:
            raise RuntimeError(f"could not locate X64/EFI/OC inside {asset_name}")

        src = os.path.join(oc_dir, "Drivers", filename)
        if not os.path.isfile(src):
            available = sorted(os.listdir(os.path.join(oc_dir, "Drivers")))
            raise RuntimeError(f"{filename} не найден в этой сборке OpenCorePkg. Доступны: {', '.join(available)}")

        dst = os.path.join(root, "Drivers", filename)
        shutil.copy2(src, dst)
        log.append(f"[Drivers] {filename} <- {build['version']}")

    return {"file": filename, "version": build["version"], "source": build["source"], "backup": backup_path}


# ------------------------------------------------------------------ scan --

def scan_root(root):
    """Read-only: no network, no writes. Returns a JSON-able dict describing
    what's on disk right now."""
    if not os.path.isdir(os.path.join(root, "Kexts")):
        raise RuntimeError(f"'{root}' doesn't look like an EFI/OC checkout (no Kexts/ found)")

    state = load_state(root)
    kexts_dir = os.path.join(root, "Kexts")

    kernel_add_status = {}
    if os.path.isfile(_config_path(root)):
        try:
            entries = _load_config(root).get("Kernel", {}).get("Add", [])
            for e in entries:
                bp = e.get("BundlePath")
                if bp:
                    kernel_add_status[bp] = bool(e.get("Enabled", False))
        except Exception:
            pass  # malformed config.plist - report kexts as present/unwired rather than fail the whole scan

    uefi_drivers_status = {}
    if os.path.isfile(_config_path(root)):
        try:
            entries = _load_config(root).get("UEFI", {}).get("Drivers", [])
            for e in entries:
                p = e.get("Path")
                if p:
                    uefi_drivers_status[p] = bool(e.get("Enabled", False))
        except Exception:
            pass

    components = []
    known_kexts = set()
    for component in load_components():
        entry = {"name": component["name"], "repo": component["repo"], "kexts": []}
        for kext in component["kexts"]:
            known_kexts.add(kext)
            path = os.path.join(kexts_dir, kext)
            wired = kext in kernel_add_status
            entry["kexts"].append({
                "bundle": kext,
                "present": os.path.isdir(path),
                "local_version": local_kext_version(path) if os.path.isdir(path) else None,
                "wired": wired,
                "enabled": kernel_add_status.get(kext) if wired else None,
            })
        components.append(entry)

    manual_kexts = []
    other_kexts = []
    if os.path.isdir(kexts_dir):
        for name in sorted(os.listdir(kexts_dir)):
            if is_junk_metadata_name(name) or not name.endswith(".kext"):
                continue
            if name in MANUAL_ONLY_KEXTS:
                manual_kexts.append(name)
            elif name not in known_kexts:
                other_kexts.append(name)

    oc_efi_path = os.path.join(root, "OpenCore.efi")
    oc_info = {"present": os.path.isfile(oc_efi_path)}
    if oc_info["present"]:
        current_hash = sha256_of(oc_efi_path)
        oc_info["sha256"] = current_hash
        recorded = state.get("opencore", {})
        oc_info["last_known_version"] = recorded.get("version")
        oc_info["last_known_channel"] = recorded.get("channel")
        oc_info["changed_since_last_update"] = recorded.get("sha256") != current_hash
        oc_info["live_booted_version"] = read_live_opencore_version()

    drivers_dir = os.path.join(root, "Drivers")
    drivers = []
    if os.path.isdir(drivers_dir):
        recorded_drivers = state.get("drivers", {})
        for fname in sorted(os.listdir(drivers_dir)):
            if is_junk_metadata_name(fname):
                continue
            fpath = os.path.join(drivers_dir, fname)
            if not os.path.isfile(fpath):
                continue
            current_hash = sha256_of(fpath)
            rec = recorded_drivers.get(fname, {})
            wired = fname in uefi_drivers_status
            drivers.append({
                "file": fname,
                "sha256": current_hash,
                "last_known_version": rec.get("version"),
                "changed_since_last_update": rec.get("sha256") != current_hash,
                "wired": wired,
                "enabled": uefi_drivers_status.get(fname) if wired else None,
            })

    resources_state = state.get("resources_theme", {})

    return {
        "root": root,
        "components": components,
        "manual_only_kexts_present": manual_kexts,
        "other_kexts_present": other_kexts,
        "opencore": oc_info,
        "drivers": drivers,
        "resources_theme": resources_state,
    }


OC_VENDOR_GUID = "4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102"


def read_live_opencore_version():
    """OpenCore itself publishes its running version as an NVRAM variable
    when Misc.Security.ExposeSensitiveData has bit 0x02 set (see OpenCore's
    own Configuration.pdf) - reading the binary directly doesn't work (no
    plain version string in it, verified against a real OpenCore.efi), but
    this does, straight from the currently booted instance.

    Important caveat this can't resolve on its own: this reflects whatever
    OpenCore is ACTUALLY booted right now, which is only the same as "the
    OpenCore.efi at the path you're inspecting" if you're currently booted
    from that exact EFI. Point this at a different partition's EFI (e.g.
    a USB test copy while booted from the internal disk) and this will
    report the disk's live version, not the USB copy's - caller/UI should
    label it accordingly rather than presenting it as verified-for-this-path.
    """
    try:
        result = subprocess.run(
            ["nvram", f"{OC_VENDOR_GUID}:opencore-version"],
            capture_output=True, text=True, timeout=10,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    # nvram prints "GUID:name\tvalue" - split on the first tab
    value = result.stdout.strip()
    if "\t" in value:
        value = value.split("\t", 1)[1]
    value = value.strip()
    return format_opencore_version(value) if value else None


def format_opencore_version(raw):
    """Raw NVRAM value looks like 'REL-107-2025-11-19' (build type -
    version digits, one per component, no dots - build date). Reformat to
    '1.0.7 (2025-11-19)' so it's directly comparable to the plain X.Y.Z
    tags GitHub releases use for "Доступная". Falls back to the untouched
    raw string if it doesn't match this exact observed shape - never
    guess at a layout that hasn't actually been seen."""
    m = re.match(r"^(?:REL|DBG|DEBUG)-(\d{2,4})-(\d{4}-\d{2}-\d{2})$", raw)
    if not m:
        return raw
    digits, date = m.groups()
    return f"{'.'.join(digits)} ({date})"


def pick_folder_native(prompt="Choose the EFI/OC folder"):
    """Real native macOS folder picker via osascript - no GUI toolkit
    dependency needed, ships on every Mac. Returns {"path": ...} or
    {"cancelled": True} (user hit Cancel) or {"unavailable": True} (not
    macOS / no osascript - caller should fall back to browse_dir())."""
    script = f'POSIX path of (choose folder with prompt "{prompt}")'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        return {"unavailable": True}

    if result.returncode != 0:
        if "User canceled" in result.stderr or "(-128)" in result.stderr:
            return {"cancelled": True}
        raise RuntimeError(result.stderr.strip() or "osascript failed")

    return {"path": result.stdout.strip()}


def looks_like_efi_oc(path):
    return os.path.isdir(os.path.join(path, "Kexts")) and os.path.isfile(os.path.join(path, "config.plist"))


def browse_dir(path):
    """Directory listing for the in-browser folder picker. The server has
    full local filesystem access (it runs on your own machine), a plain
    browser tab never can - this is what stands in for a native 'choose
    folder' dialog. Returns subdirectories only, sorted, with a flag for
    ones that already look like a real EFI/OC folder."""
    path = os.path.abspath(path or os.path.expanduser("~"))
    if not os.path.isdir(path):
        raise RuntimeError(f"'{path}' is not a directory")

    entries = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=True):
                        entries.append(entry.name)
                except OSError:
                    continue  # unreadable/broken entry - skip, don't fail the whole listing
    except PermissionError:
        raise RuntimeError(f"нет доступа к '{path}'")

    entries.sort(key=str.lower)
    parent = os.path.dirname(path) if path != os.path.dirname(path) else None
    return {
        "path": path,
        "parent": parent,
        "is_efi_oc": looks_like_efi_oc(path),
        "dirs": [
            {"name": name, "is_efi_oc": looks_like_efi_oc(os.path.join(path, name))}
            for name in entries
        ],
    }


def check_updates(root, channel):
    """One Dortania manifest fetch (covers every component at once) plus a
    per-component GitHub fallback call only where needed. Returns
    scan_root()'s data plus 'latest_version'/'source' per component/opencore."""
    data = scan_root(root)

    manifest = None
    try:
        manifest = fetch_dortania_manifest()
    except Exception as e:
        data["dortania_error"] = str(e)  # surfaced once - per-component GitHub fallback still runs below regardless

    components_by_name = {c["name"]: c for c in load_components()}
    for entry in data["components"]:
        try:
            component = components_by_name[entry["name"]]
            build = resolve_component_build(component, channel, manifest)
            entry["latest_version"] = build["version"]
            entry["release_url"] = build["html_url"]
            entry["source"] = build["source"]
            entry["outdated"] = any(k["local_version"] != build["version"] for k in entry["kexts"])
        except Exception as e:
            entry["error"] = str(e)

    try:
        build = resolve_component_build({"name": "OpenCorePkg", "repo": OPENCORE_REPO}, channel, manifest)
        data["opencore"]["latest_version"] = build["version"]
        data["opencore"]["release_url"] = build["html_url"]
        data["opencore"]["source"] = build["source"]
    except Exception as e:
        data["opencore"]["error"] = str(e)
    return data


# --------------------------------------------------------------- apply ---

def apply_kext_component(component_name, root, channel, log):
    component = next((c for c in load_components() if c["name"] == component_name), None)
    if not component:
        raise RuntimeError(f"unknown component '{component_name}'")

    backup_path = backup_oc_folder_zip(root)
    log.append(f"[{component_name}] backup -> {backup_path}")

    manifest = None
    try:
        manifest = fetch_dortania_manifest()
    except Exception as e:
        log.append(f"[{component_name}] Dortania manifest unavailable ({e}), falling back to GitHub releases")

    build = resolve_component_build(component, channel, manifest)
    asset_name = os.path.basename(build["asset_url"])
    log.append(f"[{component_name}] source={build['source']} {asset_name} -> {build['version']}")

    kexts_dir = os.path.join(root, "Kexts")
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, asset_name)
        download(build["asset_url"], zip_path)
        if build["sha256"]:
            actual = sha256_of(zip_path)
            if actual != build["sha256"]:
                raise RuntimeError(f"sha256 mismatch for {asset_name}: expected {build['sha256']}, got {actual}")
            log.append(f"[{component_name}] sha256 verified against Dortania manifest")
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)

        applied = []
        for kext in component["kexts"]:
            src = find_in_tree(extract_dir, kext)
            if not src:
                log.append(f"[{component_name}] WARNING: {kext} not found in {asset_name}, left untouched")
                continue
            dst = os.path.join(kexts_dir, kext)
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            log.append(f"[{component_name}] {kext} -> {build['version']}")
            applied.append(kext)
    return {"component": component_name, "version": build["version"], "channel": channel,
            "source": build["source"], "applied_kexts": applied, "backup": backup_path}


def apply_opencore(root, channel, parts, log):
    """parts: subset of {'efi', 'drivers', 'resources'}."""
    backup_path = backup_oc_folder_zip(root)
    log.append(f"[OpenCorePkg] backup -> {backup_path}")

    manifest = None
    try:
        manifest = fetch_dortania_manifest()
    except Exception as e:
        log.append(f"[OpenCorePkg] Dortania manifest unavailable ({e}), falling back to GitHub releases")

    build = resolve_component_build({"name": "OpenCorePkg", "repo": OPENCORE_REPO}, channel, manifest)
    tag = build["version"]
    asset_name = os.path.basename(build["asset_url"])
    log.append(f"[OpenCorePkg] source={build['source']} {asset_name} -> {tag}")

    state = load_state(root)
    result = {"version": tag, "channel": channel, "source": build["source"], "applied_parts": [], "backup": backup_path}

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, asset_name)
        download(build["asset_url"], zip_path)
        if build["sha256"]:
            actual = sha256_of(zip_path)
            if actual != build["sha256"]:
                raise RuntimeError(f"sha256 mismatch for {asset_name}: expected {build['sha256']}, got {actual}")
            log.append("[OpenCorePkg] sha256 verified against Dortania manifest")
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)

        oc_dir = None
        for dirpath, _, filenames in os.walk(extract_dir):
            if "OpenCore.efi" in filenames and "X64" in dirpath.split(os.sep):
                oc_dir = dirpath
                break
        if not oc_dir:
            raise RuntimeError(f"could not locate X64/EFI/OC inside {asset_name}")

        if "efi" in parts:
            dst = os.path.join(root, "OpenCore.efi")
            shutil.copy2(os.path.join(oc_dir, "OpenCore.efi"), dst)
            state["opencore"] = {"version": tag, "channel": channel, "sha256": sha256_of(dst)}
            log.append(f"[OpenCorePkg] OpenCore.efi -> {tag}")
            result["applied_parts"].append("efi")

        if "drivers" in parts:
            local_drivers_dir = os.path.join(root, "Drivers")
            new_drivers_dir = os.path.join(oc_dir, "Drivers")
            state.setdefault("drivers", {})
            if os.path.isdir(local_drivers_dir) and os.path.isdir(new_drivers_dir):
                for fname in os.listdir(local_drivers_dir):
                    if is_junk_metadata_name(fname):
                        continue
                    src = os.path.join(new_drivers_dir, fname)
                    dst = os.path.join(local_drivers_dir, fname)
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                        state["drivers"][fname] = {"version": tag, "sha256": sha256_of(dst)}
                        log.append(f"[OpenCorePkg] Drivers/{fname} -> {tag}")
                    else:
                        log.append(f"[OpenCorePkg] WARNING: Drivers/{fname} has no counterpart in {tag}, left as-is")
            result["applied_parts"].append("drivers")

        if "resources" in parts:
            local_resources_dir = os.path.join(root, "Resources")
            new_resources_dir = os.path.join(oc_dir, "Resources")
            if os.path.isdir(new_resources_dir):
                if os.path.isdir(local_resources_dir):
                    shutil.rmtree(local_resources_dir)
                shutil.copytree(new_resources_dir, local_resources_dir)
                state["resources_theme"] = {"source": OPENCORE_REPO, "version": tag}
                log.append(f"[OpenCorePkg] Resources/ -> stock OpenCorePkg {tag}")
            result["applied_parts"].append("resources")

    save_state(root, state)
    return result


def apply_theme(repo, root, log, ref=None):
    """repo: 'owner/name' of a GitHub repo whose tree contains a Resources/
    folder in the shape OpenCanopy expects (Image/Label/Font/Audio)."""
    backup_path = backup_oc_folder_zip(root)
    log.append(f"[theme] backup -> {backup_path}")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "theme.zip")
        log.append(f"[theme] downloading {repo} ({ref or 'default branch'}) ...")
        download_repo_archive(repo, zip_path, ref=ref)
        extract_dir = os.path.join(tmp, "extracted")
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(extract_dir)

        resources_src = find_dir_named(extract_dir, "Resources")
        if not resources_src:
            raise RuntimeError(f"no Resources/ folder found anywhere in {repo}")

        local_resources_dir = os.path.join(root, "Resources")
        if os.path.isdir(local_resources_dir):
            shutil.rmtree(local_resources_dir)
        shutil.copytree(resources_src, local_resources_dir)
        log.append(f"[theme] Resources/ <- {repo}")

    state = load_state(root)
    state["resources_theme"] = {"source": repo, "ref": ref}
    save_state(root, state)
    return {"source": repo, "backup": backup_path}


# ------------------------------------------------------- config migration --

def _merge_value(old_val, new_val, path, report):
    """Returns the merged value for one key path. `new_val` is the value
    from the NEW version's Sample.plist (i.e. the target schema/shape);
    `old_val` is what the user currently has."""
    if type(old_val) is not type(new_val) and not (
        isinstance(old_val, (int, float)) and isinstance(new_val, (int, float))
    ):
        report["type_mismatch"].append({"path": path, "old_type": type(old_val).__name__,
                                         "new_type": type(new_val).__name__})
        return new_val

    if isinstance(new_val, dict):
        result = {}
        for key, new_sub in new_val.items():
            sub_path = f"{path}.{key}" if path else key
            if key in old_val:
                result[key] = _merge_value(old_val[key], new_sub, sub_path, report)
                report["copied"].append(sub_path)
            else:
                result[key] = new_sub
                report["kept_new_default"].append(sub_path)
        for key in old_val:
            if key not in new_val:
                report["removed_in_new"].append(f"{path}.{key}" if path else key)
        return result

    if isinstance(new_val, list):
        # OpenCore arrays are lists of uniform-shaped dicts (Kernel->Add,
        # ACPI->Add, UEFI->Drivers, Booter->Patch, ...). Sample.plist ships
        # exactly one exemplar item - use it as the per-item template so
        # each of the user's real entries gets reconciled against the new
        # schema shape, key by key, instead of being replaced wholesale.
        # Plain user data (a hostlist path, an ACPI table filename, a
        # kext's own BundlePath/Enabled/Comment values) is preserved as-is;
        # only which KEYS each item has gets reconciled.
        if not new_val or not isinstance(new_val[0], dict):
            # scalar arrays (e.g. Add/Block name lists) - old data wins outright
            report["copied"].append(path + " (list, kept as-is)")
            return list(old_val)

        template = new_val[0]
        result = []
        for i, item in enumerate(old_val):
            if isinstance(item, dict):
                merged_item, _ = _merge_dict_against_template(item, template, f"{path}[{i}]", report)
                result.append(merged_item)
            else:
                result.append(item)
        report["copied"].append(f"{path} ({len(result)} item(s) carried over, reconciled against new schema)")
        return result

    # scalar leaf: old value always wins once type matches
    return old_val


def _merge_dict_against_template(old_item, template, path, report):
    result = {}
    for key, template_val in template.items():
        sub_path = f"{path}.{key}"
        if key in old_item:
            old_sub = old_item[key]
            if type(old_sub) is type(template_val) or (
                isinstance(old_sub, (int, float)) and isinstance(template_val, (int, float))
            ):
                result[key] = old_sub if not isinstance(template_val, (dict, list)) else \
                    _merge_value(old_sub, template_val, sub_path, report)
            else:
                report["type_mismatch"].append({"path": sub_path, "old_type": type(old_sub).__name__,
                                                 "new_type": type(template_val).__name__})
                result[key] = template_val
        else:
            result[key] = template_val
            report["kept_new_default"].append(sub_path)
    for key in old_item:
        if key not in template:
            # Not part of the new schema's template shape - most likely a
            # per-entry value that has no template counterpart to validate
            # against (rare). Keep it rather than silently drop user data.
            result[key] = old_item[key]
            report["removed_in_new"].append(f"{path}.{key} (kept anyway - not in new template)")
    return result, report


def migrate_config(old_config_path, new_sample_path):
    with open(old_config_path, "rb") as f:
        old_config = plistlib.load(f)
    with open(new_sample_path, "rb") as f:
        new_sample = plistlib.load(f)

    report = {"copied": [], "kept_new_default": [], "type_mismatch": [], "removed_in_new": []}
    merged = _merge_value(old_config, new_sample, "", report)
    if "" in [r for r in report["copied"] if r == ""]:
        pass  # top level path is empty string, harmless
    return merged, report
