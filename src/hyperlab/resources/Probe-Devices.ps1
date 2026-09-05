[CmdletBinding()]
param([Parameter(Mandatory=$true)][string]$OutputDirectory, [switch]$IncludeRuntimeArtifacts)

# Inventory only: no device handles, capture APIs, serial ports, or driver changes.
$ErrorActionPreference = 'Stop'
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$null = New-Item -ItemType Directory -Path $OutputDirectory -Force
$warnings = [Collections.Generic.List[string]]::new()
$propertyKeys = @(
    'DEVPKEY_Device_HardwareIds', 'DEVPKEY_Device_CompatibleIds',
    'DEVPKEY_Device_Parent', 'DEVPKEY_Device_ContainerId',
    'DEVPKEY_Device_LocationPaths', 'DEVPKEY_Device_LocationInfo',
    'DEVPKEY_Device_ProblemCode', 'DEVPKEY_Device_DriverProvider',
    'DEVPKEY_Device_DriverVersion', 'DEVPKEY_Device_DriverInfPath',
    'DEVPKEY_Device_Service', 'DEVPKEY_Device_Manufacturer',
    'DEVPKEY_Device_BusReportedDeviceDesc', 'DEVPKEY_Device_SerialNumber',
    'DEVPKEY_Device_DriverDate', 'DEVPKEY_Device_EnumeratorName'
)
function Value-OrUnknown($Value) {
    if ($null -eq $Value -or ($Value -is [string] -and $Value.Length -eq 0)) { return 'unknown' }
    return $Value
}
function Get-PEArchitecture([string]$Path) {
    if ([IO.Path]::GetExtension($Path) -notin @('.dll', '.exe', '.cti', '.sys')) { return 'not_applicable' }
    $stream = $null
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
        $reader = [IO.BinaryReader]::new($stream)
        if ($reader.ReadUInt16() -ne 0x5A4D) { return 'unknown' }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or $peOffset -gt $stream.Length - 6) { return 'unknown' }
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x4550) { return 'unknown' }
        switch ($reader.ReadUInt16()) {
            0x014C { return 'x86' }
            0x8664 { return 'x64' }
            0xAA64 { return 'arm64' }
            default { return 'unknown' }
        }
    } catch { return 'unknown' }
    finally { if ($stream) { $stream.Dispose() } }
}
function Test-ScopedRoot([string]$Path) {
    if (-not $Path -or $Path.StartsWith('\\')) { return $false }
    try { $resolved = [IO.Path]::GetFullPath($Path).TrimEnd('\') } catch { return $false }
    if ($resolved -eq [IO.Path]::GetPathRoot($resolved).TrimEnd('\')) { return $false }
    $broadRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA, $env:APPDATA, $env:USERPROFILE, $env:WINDIR, $env:ProgramData)
    return $resolved -notin $broadRoots
}

$pnp = @(Get-PnpDevice -PresentOnly | Where-Object {
    $_.InstanceId -match '^(USB|USBSTOR)\\' -or $_.Class -in @('Camera', 'Image', 'Ports')
})
$signedDrivers = @{}
try {
    foreach ($driver in Get-CimInstance Win32_PnPSignedDriver) { $signedDrivers[$driver.DeviceID] = $driver }
} catch { $warnings.Add('Signed-driver CIM inventory unavailable: ' + $_.Exception.Message) }
$devices = @(foreach ($device in $pnp) {
    $props = @{}
    # Enumerate available keys: requesting an unsupported key can discard the
    # entire keyed query on this Windows build.
    foreach ($prop in @(Get-PnpDeviceProperty -InstanceId $device.InstanceId -ErrorAction SilentlyContinue)) {
        if ($prop.KeyName -in $propertyKeys) { $props[$prop.KeyName] = $prop.Data }
    }
    if ($props.Count -eq 0) { $warnings.Add('Device properties unavailable for ' + $device.FriendlyName) }
    $usbVid = 'unknown'; $usbPid = 'unknown'; $interfaceNumber = 'unknown'
    if ($device.InstanceId -match 'VID_([0-9A-F]{4})') { $usbVid = $Matches[1].ToUpperInvariant() }
    if ($device.InstanceId -match 'PID_([0-9A-F]{4})') { $usbPid = $Matches[1].ToUpperInvariant() }
    if ($device.InstanceId -match '&MI_([0-9A-F]{2})') { $interfaceNumber = $Matches[1].ToUpperInvariant() }
    $compatible = @($props['DEVPKEY_Device_CompatibleIds'] | Where-Object { $null -ne $_ })
    $classes = @(foreach ($id in $compatible) {
        if ($id -match '^USB\\Class_([0-9A-F]{2})(?:&SubClass_([0-9A-F]{2}))?(?:&Prot_([0-9A-F]{2}))?$') {
            [ordered]@{ class = $Matches[1]; subclass = (Value-OrUnknown $Matches[2]); protocol = (Value-OrUnknown $Matches[3]); source = $id }
        }
    })
    $service = $props['DEVPKEY_Device_Service']
    $servicePath = 'unknown'
    if ($service) {
        $serviceEntry = Get-ItemProperty -LiteralPath ('HKLM:\SYSTEM\CurrentControlSet\Services\' + $service) -ErrorAction SilentlyContinue
        if ($serviceEntry.ImagePath) { $servicePath = $serviceEntry.ImagePath }
    }
    $signed = $signedDrivers[$device.InstanceId]
    [ordered]@{
        instance_id = $device.InstanceId; present = $true; status = $device.Status
        class = (Value-OrUnknown $device.Class); friendly_name = (Value-OrUnknown $device.FriendlyName)
        hardware_ids = @($props['DEVPKEY_Device_HardwareIds'] | Where-Object { $null -ne $_ })
        compatible_ids = $compatible; vid = $usbVid; pid = $usbPid; interface = $interfaceNumber
        manufacturer = (Value-OrUnknown $props['DEVPKEY_Device_Manufacturer'])
        serial = (Value-OrUnknown $props['DEVPKEY_Device_SerialNumber'])
        serial_note = 'Only an explicit serial property is reported; instance ID may contain identifying information.'
        parent = (Value-OrUnknown $props['DEVPKEY_Device_Parent'])
        container_id = (Value-OrUnknown $props['DEVPKEY_Device_ContainerId'])
        location_paths = @($props['DEVPKEY_Device_LocationPaths'] | Where-Object { $null -ne $_ })
        location = (Value-OrUnknown $props['DEVPKEY_Device_LocationInfo'])
        problem_code = (Value-OrUnknown $props['DEVPKEY_Device_ProblemCode'])
        driver = [ordered]@{
            provider = (Value-OrUnknown $props['DEVPKEY_Device_DriverProvider'])
            version = (Value-OrUnknown $props['DEVPKEY_Device_DriverVersion'])
            inf = (Value-OrUnknown $props['DEVPKEY_Device_DriverInfPath'])
            date = (Value-OrUnknown $props['DEVPKEY_Device_DriverDate'])
            service = (Value-OrUnknown $service); service_image_path = $servicePath
            signed = $(if ($signed) { $signed.IsSigned } else { 'unknown' })
            signer = $(if ($signed) { Value-OrUnknown $signed.Signer } else { 'unknown' })
        }
        bus_reported_description = (Value-OrUnknown $props['DEVPKEY_Device_BusReportedDeviceDesc'])
        enumerator = (Value-OrUnknown $props['DEVPKEY_Device_EnumeratorName'])
        usb_class_descriptors = $classes; descriptor_source = 'Windows compatible IDs; not a raw descriptor read'
        endpoints = 'unknown'; physical_association = 'IDENTITY_UNCONFIRMED'
    }
})

$related = '(?i)HinaLea|TruTag|TruScope|MATRIX VISION|mvIMPACT|mvBlueFOX|GenICam|GenTL|Pleora|eBUS|Basler|Point Grey|Spinnaker|Allied Vision|Vimba'
$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
)
$software = @(foreach ($registryRoot in $uninstallRoots) {
    foreach ($entry in @(Get-ItemProperty -Path $registryRoot -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -match $related })) {
        [ordered]@{
            name = $entry.DisplayName; version = (Value-OrUnknown $entry.DisplayVersion)
            publisher = (Value-OrUnknown $entry.Publisher); install_location = (Value-OrUnknown $entry.InstallLocation)
            registry_key = $entry.PSPath
        }
    }
})
$searchRoots = [Collections.Generic.List[string]]::new()
foreach ($entry in $software) {
    if ($entry.install_location -ne 'unknown' -and (Test-ScopedRoot $entry.install_location) -and (Test-Path -LiteralPath $entry.install_location -PathType Container)) {
        $resolved = [IO.Path]::GetFullPath($entry.install_location).TrimEnd('\')
        $searchRoots.Add($resolved)
    }
}
foreach ($programRoot in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
    if ($programRoot -and (Test-Path -LiteralPath $programRoot)) {
        foreach ($directory in @(Get-ChildItem -LiteralPath $programRoot -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match $related })) {
            $searchRoots.Add($directory.FullName)
        }
    }
}
$gentlPaths = [ordered]@{}
foreach ($variable in @('GENICAM_GENTL32_PATH', 'GENICAM_GENTL64_PATH')) {
    $value = [Environment]::GetEnvironmentVariable($variable)
    $gentlPaths[$variable] = Value-OrUnknown $value
    foreach ($directory in @($value -split ';' | Where-Object { $_ })) {
        if ((Test-ScopedRoot $directory) -and (Test-Path -LiteralPath $directory -PathType Container)) {
            $searchRoots.Add([IO.Path]::GetFullPath($directory))
        } else { $warnings.Add('A configured GenTL search root was missing, broad, or nonlocal and was not searched.') }
    }
}
$searchRoots = @($searchRoots | Sort-Object -Unique)
$extensions = @('.cti', '.dll', '.exe', '.msi', '.inf', '.h', '.hpp', '.xml', '.ini', '.json', '.cal', '.lut', '.hdr', '.dat', '.log', '.txt')
$artifacts = @(foreach ($directory in $searchRoots) {
    foreach ($file in @(Get-ChildItem -LiteralPath $directory -File -Recurse:$IncludeRuntimeArtifacts -ErrorAction SilentlyContinue | Where-Object {
        ($IncludeRuntimeArtifacts -or $_.Extension -eq '.cti') -and
        $_.Extension.ToLowerInvariant() -in $extensions -and $_.FullName -notlike '*\local\diagnostics\*'
    })) {
        [ordered]@{ path = $file.FullName; bytes = $file.Length; extension = $file.Extension; architecture = (Get-PEArchitecture $file.FullName); executed = $false }
    }
})
$os = Get-CimInstance Win32_OperatingSystem
$snapshot = [ordered]@{
    schema_version = 1; captured_at = [DateTimeOffset]::Now.ToString('o'); mode = 'inventory_read_only'
    environment = [ordered]@{
        os = $os.Caption; os_version = $os.Version; os_architecture = $os.OSArchitecture
        powershell = $PSVersionTable.PSVersion.ToString(); process_64bit = [Environment]::Is64BitProcess
        gentl_paths = $gentlPaths
    }
    scope = [ordered]@{
        device_filter = 'All present USB/USBSTOR instance IDs and Camera/Image/Ports classes'
        file_search_roots = $searchRoots; software_source = 'Uninstall registry only; no Win32_Product'
        recursive_runtime_artifacts = [bool]$IncludeRuntimeArtifacts
        driver_files = 'Associated INF/service paths recorded; no driver DLL is loaded'
        forbidden_actions_performed = @(); serial_ports_opened = $false; camera_streams_opened = $false
        full_disk_search = $false; binaries_executed = $false
    }
    devices = $devices; software = $software; artifacts = $artifacts; warnings = @($warnings)
}
$jsonPath = Join-Path $OutputDirectory 'snapshot.json'
if (Test-Path -LiteralPath $jsonPath) { throw "Snapshot already exists; choose a fresh output directory: $OutputDirectory" }
$snapshot | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $jsonPath -Encoding utf8
$lines = [Collections.Generic.List[string]]::new()
$lines.Add('PRIVATE local device inventory - may include complete device identifiers')
$lines.Add('Captured: ' + $snapshot.captured_at)
$lines.Add('Read-only; no camera, serial, or producer opened. Endpoints unknown.')
foreach ($device in $devices) {
    $lines.Add('')
    $lines.Add($device.friendly_name + ' [' + $device.class + '] ' + $device.status + ' problem=' + $device.problem_code)
    $lines.Add('  ID: ' + $device.instance_id)
    $lines.Add('  VID/PID/MI: ' + $device.vid + '/' + $device.pid + '/' + $device.interface)
    $lines.Add('  Bus description: ' + $device.bus_reported_description)
    $lines.Add('  Parent: ' + $device.parent + ' Container: ' + $device.container_id)
    $lines.Add('  Location: ' + ($device.location_paths -join '; '))
    $lines.Add('  Driver: ' + $device.driver.provider + ' ' + $device.driver.version + ' ' + $device.driver.inf + ' service=' + $device.driver.service)
    $lines.Add('  Compatible IDs: ' + ($device.compatible_ids -join '; '))
}
$lines.Add('')
$lines.Add('Related software: ' + $software.Count + '; scoped artifacts: ' + $artifacts.Count)
$lines.Add('Search roots: ' + ($searchRoots -join '; '))
foreach ($warning in $warnings) { $lines.Add('WARNING: ' + $warning) }
$lines | Set-Content -LiteralPath (Join-Path $OutputDirectory 'inventory.txt') -Encoding utf8
Write-Output $jsonPath
