from opentrons import protocol_api

metadata = {"protocolName": "Transfer 100 uL from A1 to B1", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    tips = protocol.load_labware("opentrons_96_tiprack_300ul", 1)
    plate = protocol.load_labware("corning_96_wellplate_360ul_flat", 2)
    pipette = protocol.load_instrument("p300_single_gen2", "right", tip_racks=[tips])
    pipette.transfer(100, plate["A1"], plate["B1"])
