from aero_audit.ingest.faa_status import parse_status

XML = """<AIRPORT_STATUS_INFORMATION><Update_Time>Thu Sep 10 13:12:08 2026 GMT</Update_Time>
<Delay_type><Name>Ground Delay Programs</Name><Ground_Delay_List><Ground_Delay><ARPT>MIA</ARPT><Reason>disabled aircraft on the runway</Reason><Avg>52 minutes</Avg><Max>1 hour and 32 minutes</Max></Ground_Delay></Ground_Delay_List></Delay_type>
<Delay_type><Name>Ground Stop Programs</Name><Ground_Stop_List><Program><ARPT>EWR</ARPT><Reason>thunderstorms</Reason><End_Time>2:00 pm EDT</End_Time></Program></Ground_Stop_List></Delay_type>
<Delay_type><Name>General Arrival/Departure Delay Info</Name><Arrival_Departure_Delay_List><Delay><ARPT>SFO</ARPT><Reason>low ceilings</Reason><Arrival_Departure Type="Arrival"><Min>31 minutes</Min><Max>45 minutes</Max><Trend>Increasing</Trend></Arrival_Departure></Delay></Arrival_Departure_Delay_List></Delay_type>
</AIRPORT_STATUS_INFORMATION>"""


def test_parse_status_normalises_all_kinds():
    d = parse_status(XML)
    assert d["updated"].startswith("Thu Sep 10")
    by = {e["airport"]: e for e in d["entries"]}
    assert by["MIA"]["kind"] == "ground delay program" and by["MIA"]["avg"] == "52 minutes"
    assert by["EWR"]["kind"] == "ground stop" and by["EWR"]["end_time"] == "2:00 pm EDT"
    assert by["SFO"]["direction"] == "arrival" and by["SFO"]["trend"] == "Increasing"
