"""
Test script for ifc_group functionality

This script demonstrates how to test ifc_group.annotate_group()
outside of Grasshopper for debugging purposes.
"""

import sys
sys.path.append(r"d:\Kevin\GH\ifc_test\py_modules")

from ifc_group import annotate_group


def test_single_group():
    """Test: Single group for all objects"""
    print("\n=== Test 1: Single group ===")

    # Simulate GH wrappers
    obj = [
        ["geo1", "Panel_A"],
        ["geo2", "Panel_B"],
        ["geo3", "Panel_C"],
    ]

    result, log = annotate_group(obj, "Zone_A")
    print(log)

    # Check results
    for i, item in enumerate(result):
        print(f"Item {i}: {item}")
        assert len(item) == 3, "Should have 3 elements"
        assert item[2] == {"groups": ["Zone_A"]}, "Should have Zone_A group"

    print("✓ Test 1 passed")


def test_multiple_groups():
    """Test: Multiple groups for all objects"""
    print("\n=== Test 2: Multiple groups ===")

    obj = [
        ["geo1", "Panel_A"],
        ["geo2", "Panel_B"],
    ]

    result, log = annotate_group(obj, ["Zone_A", "Phase_1"])
    print(log)

    for i, item in enumerate(result):
        print(f"Item {i}: {item}")
        assert item[2] == {"groups": ["Zone_A", "Phase_1"]}, "Should have both groups"

    print("✓ Test 2 passed")


def test_group_merge():
    """Test: Merging groups (calling annotate_group twice)"""
    print("\n=== Test 3: Group merge ===")

    obj = [
        ["geo1", "Panel_A", {"groups": ["Zone_A"]}],  # Already has Zone_A
    ]

    # Add Phase_1 to existing groups
    result, log = annotate_group(obj, "Phase_1")
    print(log)

    item = result[0]
    print(f"Result: {item}")
    assert item[2]["groups"] == ["Zone_A", "Phase_1"], "Should merge groups"

    print("✓ Test 3 passed")


def test_with_existing_override():
    """Test: Groups with existing override_data"""
    print("\n=== Test 4: Groups with existing override ===")

    obj = [
        ["geo1", "Panel_A", {"Pset_Override": {"CustomProp": "Value1"}}],
    ]

    result, log = annotate_group(obj, "Zone_A")
    print(log)

    item = result[0]
    print(f"Result: {item}")
    assert item[2]["groups"] == ["Zone_A"], "Should add groups"
    assert item[2]["Pset_Override"] == {"CustomProp": "Value1"}, "Should preserve existing override"

    print("✓ Test 4 passed")


def test_empty_groups():
    """Test: Empty group names are filtered out"""
    print("\n=== Test 5: Empty groups filtered ===")

    obj = [
        ["geo1", "Panel_A"],
    ]

    result, log = annotate_group(obj, ["Zone_A", "", "  ", "Phase_1"])
    print(log)

    item = result[0]
    print(f"Result: {item}")
    assert item[2]["groups"] == ["Zone_A", "Phase_1"], "Should filter empty strings"

    print("✓ Test 5 passed")


def test_no_groups():
    """Test: No groups provided"""
    print("\n=== Test 6: No groups provided ===")

    obj = [
        ["geo1", "Panel_A"],
    ]

    result, log = annotate_group(obj, "")
    print(log)

    # Should pass through unchanged
    assert result == obj, "Should be unchanged"

    print("✓ Test 6 passed")


if __name__ == "__main__":
    print("Testing ifc_group module...")

    try:
        test_single_group()
        test_multiple_groups()
        test_group_merge()
        test_with_existing_override()
        test_empty_groups()
        test_no_groups()

        print("\n" + "="*50)
        print("✓ All tests passed!")
        print("="*50)

    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
