from unittest.mock import MagicMock, patch

import pytest


class TestExecuteQasm3:
    @patch("app.task_processor.AerSimulator")
    @patch("app.task_processor.loads")
    def test_execute_valid_circuit(self, mock_loads, mock_aer_cls):
        mock_circuit = MagicMock()
        mock_loads.return_value = mock_circuit
        mock_sim = MagicMock()
        mock_aer_cls.return_value = mock_sim
        mock_result = MagicMock()
        mock_result.get_counts.return_value = {"0": 60, "1": 40}
        mock_sim.run.return_value.result.return_value = mock_result

        from app.task_processor import execute_qasm3
        result = execute_qasm3("OPENQASM 3; qubit q;", shots=100)

        assert isinstance(result, dict)
        assert result == {"0": 60, "1": 40}
        mock_loads.assert_called_once_with("OPENQASM 3; qubit q;")
        mock_sim.run.assert_called_once_with(mock_circuit, shots=100)

    @patch("app.task_processor.AerSimulator")
    @patch("app.task_processor.loads")
    def test_counts_sum_equals_shots(self, mock_loads, mock_aer_cls):
        mock_result = MagicMock()
        mock_result.get_counts.return_value = {"00": 128, "01": 64, "10": 32, "11": 32}
        mock_aer_cls.return_value.run.return_value.result.return_value = mock_result

        from app.task_processor import execute_qasm3
        result = execute_qasm3("OPENQASM 3;", shots=256)
        assert sum(result.values()) == 256

    @patch("app.task_processor.AerSimulator")
    @patch("app.task_processor.loads")
    def test_counts_values_are_plain_ints(self, mock_loads, mock_aer_cls):
        """Ensure non-int types are cast to plain int via int()."""
        mock_result = MagicMock()

        class FakeNumpyInt:
            def __init__(self, val):
                self._val = val
            def __int__(self):
                return self._val
            def __str__(self):
                return str(self._val)

        mock_result.get_counts.return_value = {"0": FakeNumpyInt(60), "1": FakeNumpyInt(40)}
        mock_aer_cls.return_value.run.return_value.result.return_value = mock_result

        from app.task_processor import execute_qasm3
        result = execute_qasm3("OPENQASM 3;", shots=100)
        for v in result.values():
            assert type(v) is int
        assert result == {"0": 60, "1": 40}

    @patch("app.task_processor.AerSimulator")
    @patch("app.task_processor.loads")
    def test_execute_invalid_qasm3_raises(self, mock_loads, mock_aer_cls):
        mock_loads.side_effect = Exception("Invalid QASM3")

        from app.task_processor import execute_qasm3
        with pytest.raises(Exception, match="Invalid QASM3"):
            execute_qasm3("this is not valid qasm3", shots=100)
