"""This module contains the main process of the robot."""

import json
import time
from datetime import datetime

import uiautomation
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueElement, QueueStatus
from itk_dev_shared_components.boliglaan.search import search_advis
from itk_dev_shared_components.boliglaan import common as boliglaan
import itk_dev_event_log as event_log

from robot_framework import config


def process(orchestrator_connection: OrchestratorConnection) -> None:
    """Do the primary process of the robot."""
    orchestrator_connection.log_trace("Running process.")

    event_log.setup_logging(orchestrator_connection.get_constant(config.EVENT_LOG).value)

    boliglaan.get_boliglaan().Maximize()
    boliglaan.pin_sidebar()
    search_advis.search_advis(types=["Lånets saldo = 0 kr."])

    advis_list = search_advis.get_advis_list()
    orchestrator_connection.log_info(f"Cases in list: {len(advis_list)}")

    advis_caseworkers = json.loads(orchestrator_connection.process_arguments)["advis_caseworkers"]

    for advis in advis_list:
        if "Kautionslån" in advis.case_type:
            continue

        queue_element = get_queue_element(advis.cpr, advis.case_number, orchestrator_connection)
        if not queue_element:
            orchestrator_connection.log_info("Skipping already handled case.")
            continue

        message = handle_case(advis.cpr, advis.case_number, advis_caseworkers)

        if message:
            orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE, message=f"Skipped: {message}")
            event_log.emit(orchestrator_connection.process_name, "Skipped case")
            orchestrator_connection.log_info(f"Skipping case: {message}")
        else:
            orchestrator_connection.set_queue_element_status(queue_element.id, QueueStatus.DONE)
            event_log.emit(orchestrator_connection.process_name, "Closed case")
            orchestrator_connection.log_info("Case closed")


def get_queue_element(cpr: str, case_number: str, orchestrator_connection: OrchestratorConnection) -> QueueElement | None:
    """Check if the case has been successfully handled before.
    If not create a new queue element for it.

    Returns:
        A QueueElement object if the case should be handled else None.
    """
    reference = f"{cpr}: {case_number}"

    # Check for already done task
    qe = orchestrator_connection.get_queue_elements(config.QUEUE_NAME, reference=reference, status=QueueStatus.DONE)
    if qe:
        return None

    return orchestrator_connection.create_queue_element(config.QUEUE_NAME, reference=reference, created_by="Robot")


def handle_case(cpr: str, case_number: str, advis_caseworkers: list[str]) -> str | None:
    """Handle the given case.

    Args:
        advis_caseworkers: A list of caseworkers who's advis should be closed.

    If the case is skipped for any reason a message is returned.
    If the case is closed successfully None is returned.
    """
    search_advis.select_advis(cpr, case_number)
    boliglaan.wait_for_case_load(cpr, case_number)

    # Check remaining debt
    boliglaan_window = boliglaan.get_boliglaan()
    debt_text: uiautomation.TextControl = boliglaan_window.CustomControl(ClassName="LaanTagerOplysningerUserControl", searchDepth=6).TextControl(Name="Restgæld:").GetNextSiblingControl()

    if debt_text.Name != "0,00":
        return "Remaining debt is not 0,00"

    # Check for signature
    tab = boliglaan.select_tab("Dokumentunderskrifter")
    document_list = tab.PaneControl(AutomationId="dataPresenter", searchDepth=5).GetChildren()

    if len(document_list) == 0:
        return "No documents"

    state = document_list[0].CustomControl(foundIndex=4).GetPattern(uiautomation.PatternId.ValuePattern).Value

    if state != "Godkendt":
        return "Document not accepted"

    # Check for 'Opkrævninger' in the future
    tab = boliglaan.select_tab("Låneafvikling")
    group = tab.GroupControl(Name="Opkrævninger", searchDepth=4)
    pane = group.PaneControl(AutomationId="dataPresenter")
    for row in pane.GetChildren():
        type_ = row.CustomControl(foundIndex=2).GetPattern(uiautomation.PatternId.ValuePattern).Value
        if type_ == "IBERO":
            date_str = row.CustomControl(foundIndex=1).GetPattern(uiautomation.PatternId.ValuePattern).Value
            if datetime.strptime(date_str, "%d-%m-%Y") > datetime.today():
                return "'I bero' on a future date"

    # Handle advis
    tab = boliglaan.select_tab("Advis")
    rows = tab.PaneControl(AutomationId="dataPresenter", searchDepth=4).GetChildren()
    for row in rows:
        state_column_value_pattern: uiautomation.ValuePattern = row.CustomControl(foundIndex=4).GetPattern(uiautomation.PatternId.ValuePattern)
        created_by = row.CustomControl(foundIndex=5).GetPattern(uiautomation.PatternId.ValuePattern).Value
        if state_column_value_pattern.Value == "UBEHANDLET" and created_by in advis_caseworkers:
            state_column_value_pattern.SetValue("FAERDIG")

    # Set case state
    tab = boliglaan.select_tab("Låneafvikling")
    group = tab.GroupControl(Name="Lån status", searchDepth=4)

    # Find the midpoint between the column header and the first row
    rect = group.HeaderItemControl(Name="Status").BoundingRectangle
    uiautomation.Click(x=rect.xcenter(), y=rect.ycenter()+rect.height())

    # Select 'Indfriet'
    popup = boliglaan_window.WindowControl(searchDepth=1)
    popup.TextControl(Name="Indfriet").GetParentControl().Click(simulateMove=False)

    # Save
    boliglaan.save_case()

    # Give Boliglån a little breathing room
    time.sleep(2)

    return None


if __name__ == '__main__':
    import os
    import uuid
    conn_string = os.getenv("OpenOrchestratorConnString")
    crypto_key = os.getenv("OpenOrchestratorKey")
    oc = OrchestratorConnection("Boliglån indfriede lån", conn_string, crypto_key, '{"advis_caseworkers":["AZ123456"]}', "trigger_id", uuid.uuid4())
    process(oc)
