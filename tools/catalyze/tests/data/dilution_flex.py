from opentrons import protocol_api

metadata = {"protocolName": "Serial dilution, 1:2 across row A"}
requirements = {"robotType": "Flex", "apiLevel": "2.20"}


def run(protocol: protocol_api.ProtocolContext):
    tips = protocol.load_labware("opentrons_flex_96_tiprack_200ul", "D1")
    reservoir = protocol.load_labware("nest_12_reservoir_15ml", "D2")
    plate = protocol.load_labware("nest_96_wellplate_200ul_flat", "D3")
    protocol.load_trash_bin("A3")
    pipette = protocol.load_instrument("flex_1channel_1000", "left", tip_racks=[tips])
    pipette.transfer(100, reservoir["A1"], plate.rows()[0][1:])
    pipette.transfer(200, reservoir["A2"], plate["A1"])
    pipette.transfer(100, plate.rows()[0][:11], plate.rows()[0][1:], mix_after=(3, 50))
