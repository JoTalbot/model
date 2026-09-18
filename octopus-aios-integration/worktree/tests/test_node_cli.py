import pytest
from click.testing import CliRunner

from node import cli


@pytest.fixture
def runner():
    return CliRunner()


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Immortal Swarm" in result.output


def test_cli_status_command_exists(runner):
    result = runner.invoke(cli, ["status", "--help"])
    assert result.exit_code == 0


def test_cli_nodes_command_exists(runner):
    result = runner.invoke(cli, ["nodes", "--help"])
    assert result.exit_code == 0


def test_cli_task_command_exists(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0


def test_cli_chat_command_exists(runner):
    result = runner.invoke(cli, ["chat", "--help"])
    assert result.exit_code == 0
    assert "Interactive" in result.output or "chat" in result.output.lower()


def test_cli_task_with_agents_option(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    assert "--agents" in result.output


def test_cli_task_with_json_option(runner):
    result = runner.invoke(cli, ["task", "--help"])
    assert result.exit_code == 0
    assert "--json" in result.output


def test_cli_memory_insert_and_query_json(runner, tmp_path):
    cfg = tmp_path / "config.yaml"
    scratch = tmp_path / "scratch"
    cfg.write_text(
        "\n".join(
            [
                "memory_facade:",
                "  scratch_root: " + str(scratch).replace("\\", "/"),
            ]
        ),
        encoding="utf-8",
    )

    ins = runner.invoke(
        cli,
        [
            "memory",
            "insert",
            "--table",
            "orders",
            "--tags",
            "car,service",
            "--data",
            '{"title":"Oil change","price":120}',
            "--config",
            str(cfg),
        ],
    )
    assert ins.exit_code == 0
    assert "ref:file:" in ins.output

    qry = runner.invoke(
        cli,
        [
            "memory",
            "query",
            "--table",
            "orders",
            "--tag",
            "service",
            "--text",
            "Oil",
            "--json",
            "--config",
            str(cfg),
        ],
    )
    assert qry.exit_code == 0
    assert '"title": "Oil change"' in qry.output


def test_cli_memory_query_supports_where_order_offset(runner, tmp_path):
    cfg = tmp_path / "config.yaml"
    scratch = tmp_path / "scratch"
    cfg.write_text(
        "\n".join(
            [
                "memory_facade:",
                "  scratch_root: " + str(scratch).replace("\\", "/"),
            ]
        ),
        encoding="utf-8",
    )

    for payload in ('{"name":"A","price":300}', '{"name":"B","price":100}', '{"name":"C","price":200}'):
        ins = runner.invoke(
            cli,
            [
                "memory",
                "insert",
                "--table",
                "offers",
                "--data",
                payload,
                "--attrs",
                '{"vendor":"x"}' if "C" not in payload else '{"vendor":"y"}',
                "--config",
                str(cfg),
            ],
        )
        assert ins.exit_code == 0

    qry = runner.invoke(
        cli,
        [
            "memory",
            "query",
            "--table",
            "offers",
            "--where",
            "attrs.vendor == 'x' and data.price >= 100",
            "--order-by",
            "data.price:asc",
            "--offset",
            "1",
            "--json",
            "--config",
            str(cfg),
        ],
    )
    assert qry.exit_code == 0
    assert '"name": "A"' in qry.output
    assert '"name": "B"' not in qry.output


def test_cli_memory_query_human_readable_output(runner, tmp_path):
    cfg = tmp_path / "config.yaml"
    scratch = tmp_path / "scratch"
    cfg.write_text(
        "\n".join(
            [
                "memory_facade:",
                "  scratch_root: " + str(scratch).replace("\\", "/"),
            ]
        ),
        encoding="utf-8",
    )

    ins = runner.invoke(
        cli,
        [
            "memory",
            "insert",
            "--table",
            "notes",
            "--tags",
            "demo",
            "--data",
            '{"title":"Hello","body":"world"}',
            "--attrs",
            '{"author":"tester"}',
            "--config",
            str(cfg),
        ],
    )
    assert ins.exit_code == 0

    qry = runner.invoke(
        cli,
        [
            "memory",
            "query",
            "--table",
            "notes",
            "--tag",
            "demo",
            "--config",
            str(cfg),
        ],
    )
    assert qry.exit_code == 0
    assert "rows=1" in qry.output
    assert "table=notes" in qry.output
    assert "title=Hello" in qry.output
    assert "author=tester" in qry.output
