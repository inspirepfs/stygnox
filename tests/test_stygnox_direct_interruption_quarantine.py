"""C3j: actual digest-bound blocked controller/transaction replacements."""
from __future__ import annotations

from copy import deepcopy
import unittest

from stygnox import direct_interruption as recovery
from stygnox import direct_interruption_binding as binding
from stygnox import direct_interruption_publication as publication
from stygnox import direct_interruption_quarantine as quarantine
from stygnox import direct_interruption_transfer as transfer
from stygnox import direct_interruption_successor as successor
from tests.test_stygnox_direct_interruption_supervisor import _evidence
from tests.test_stygnox_direct_interruption_successor import _inputs


def seal(value, key='record_sha256'):
    copy = deepcopy(value)
    copy.pop(key, None)
    copy[key] = recovery._digest(copy)
    return copy


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        self.values = _inputs()
        self.old_controller = self.values['controller_record']
        self.old_transaction = self.values['transaction_record']

    def project(self):
        return quarantine.build_quarantine_binding(
            fenced_plan=self.values['current_plan'], journal=self.values['journal'],
            witness=self.values['witness'], predecessor_controller=self.old_controller,
            predecessor_transaction=self.old_transaction)

    def test_controller_and_transaction_are_both_disabled_and_exactly_bound(self):
        projection = self.project()
        ctrl, tx, receipt = projection.values()
        self.assertFalse(ctrl['enabled'])
        self.assertFalse(ctrl['controller_execution_enabled'])
        self.assertFalse(ctrl['provider_execution_ready'])
        self.assertEqual(ctrl['installed_command'], self.values['installed_identity']['executable'])
        self.assertEqual(tx['state'], 'RECOVERY_QUARANTINED')
        self.assertFalse(tx['authority']['controller_execution'])
        self.assertEqual(ctrl['transaction_id'], tx['transaction_id'])
        self.assertEqual(receipt['predecessor_controller_record_sha256'], self.old_controller['record_sha256'])
        self.assertEqual(receipt['predecessor_transaction_record_sha256'], self.old_transaction['record_sha256'])
        self.assertFalse(receipt['successor_execution_authorised'])
        self.assertFalse(receipt['installed_successor_identity_verified'])
        self.assertFalse(receipt['handoff_admissible'])
        self.assertEqual(self.values['current_plan']['controller_record_sha256'], self.old_controller['record_sha256'])
        self.assertEqual(self.values['current_plan']['transaction_record_sha256'], self.old_transaction['record_sha256'])

    def test_installed_inspector_recognises_exact_quarantine_and_remains_blocked(self):
        projection = self.project()
        self.values['controller_record'] = projection['controller']
        self.values['transaction_record'] = projection['transaction']
        self.values['quarantine_record'] = projection['receipt']
        result = successor.validate_blocked_snapshot(**self.values)
        self.assertTrue(result['exact_blocked_lineage'])
        self.assertTrue(result['quarantined_controller_transaction_records'])
        self.assertTrue(result['installed_successor_identity_verified'])
        self.assertFalse(result['successor_execution_authorised'])
        self.assertFalse(result['handoff_admissible'])

    def test_stale_controller_refused_even_if_self_resealed(self):
        projection = self.project()
        stale = seal({**projection['controller'], 'enabled': True})
        with self.assertRaises(quarantine.QuarantineRefused):
            quarantine.validate_quarantine_binding(
                fenced_plan=self.values['current_plan'], journal=self.values['journal'],
                witness=self.values['witness'], controller_record=stale,
                transaction_record=projection['transaction'],
                quarantine_record=projection['receipt'])

    def test_stale_transaction_refused_even_if_self_resealed(self):
        projection = self.project()
        stale = seal({**projection['transaction'], 'state': 'ACTIVE'})
        with self.assertRaises(quarantine.QuarantineRefused):
            quarantine.validate_quarantine_binding(
                fenced_plan=self.values['current_plan'], journal=self.values['journal'],
                witness=self.values['witness'], controller_record=projection['controller'],
                transaction_record=stale, quarantine_record=projection['receipt'])

    def test_self_resealed_forged_quarantine_receipt_refused(self):
        projection = self.project()
        forged = seal({**projection['receipt'], 'original_binding_retired': True})
        with self.assertRaises(quarantine.QuarantineRefused):
            quarantine.validate_quarantine_binding(
                fenced_plan=self.values['current_plan'], journal=self.values['journal'],
                witness=self.values['witness'], controller_record=projection['controller'],
                transaction_record=projection['transaction'], quarantine_record=forged)

    def test_substituted_witness_refused(self):
        self.values['witness'] = seal({**self.values['witness'],
                                      'predecessor_installed_command': '/swapped'})
        with self.assertRaises(quarantine.QuarantineRefused):
            self.project()

    def test_source_plan_authority_escalation_refused(self):
        self.values['current_plan'] = seal({**self.values['current_plan'],
                                              'execution_authority_granted': True})
        with self.assertRaises(quarantine.QuarantineRefused):
            self.project()

    def test_non_quarantine_legacy_snapshot_still_readable_and_blocked(self):
        result = successor.validate_blocked_snapshot(**self.values)
        self.assertFalse(result['quarantined_controller_transaction_records'])
        self.assertFalse(result['successor_execution_authorised'])

    def test_missing_or_mutated_quarantine_rejected_by_installed_inspector(self):
        projection = self.project()
        self.values['controller_record'] = projection['controller']
        self.values['transaction_record'] = projection['transaction']
        self.values['quarantine_record'] = seal({**projection['receipt'],
                                                   'handoff_admissible': True})
        with self.assertRaises(successor.SuccessorInspectionRefused):
            successor.validate_blocked_snapshot(**self.values)
