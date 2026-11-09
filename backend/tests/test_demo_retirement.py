from pathlib import Path
import pytest
def test_retired_cli_exits_before_any_database_or_model_import():
    root=Path(__file__).parent/'legacy_support'
    checked=[]
    for path in root.rglob('*.py'):
        source=path.read_text(encoding='utf-8-sig')
        if 'RETIRED_TEST_FIXTURE_ONLY' not in source:continue
        with pytest.raises(SystemExit,match='RETIRED_TEST_FIXTURE_ONLY'):
            exec(compile(source,str(path),'exec'),{'__name__':'__main__'})
        checked.append(path)
    assert len(checked)==12
