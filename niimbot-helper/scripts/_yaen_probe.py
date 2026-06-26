import usb.core, usb.util, sys

dev = usb.core.find(idVendor=0x6868, idProduct=0x0200)
if dev is None:
    print("Device not found by pyusb")
    sys.exit(1)

print(f"Found device: {dev.idVendor:#06x}:{dev.idProduct:#06x}")
try:
    print(f"Manufacturer: {usb.util.get_string(dev, dev.iManufacturer)}")
    print(f"Product     : {usb.util.get_string(dev, dev.iProduct)}")
except Exception as e:
    print(f"(string descriptors unavailable: {e})")

for cfg in dev:
    print(f"\nConfig {cfg.bConfigurationValue}:")
    for intf in cfg:
        cls = intf.bInterfaceClass
        sub = intf.bInterfaceSubClass
        proto = intf.bInterfaceProtocol
        print(f"  Interface {intf.bInterfaceNumber}  class=0x{cls:02X} sub=0x{sub:02X} proto=0x{proto:02X}")
        for ep in intf:
            direction = "IN " if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
            eptype = ["Control", "Isochronous", "Bulk", "Interrupt"][ep.bmAttributes & 0x03]
            print(f"    EP 0x{ep.bEndpointAddress:02X}  {direction}  {eptype}  maxpkt={ep.wMaxPacketSize}")
