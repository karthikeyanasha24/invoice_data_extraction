"""
Test script to verify safe_float_conversion handles comma-separated numbers correctly.
"""

def safe_float_conversion(value, default=0.0):
    """
    Safely convert a value to float, handling comma separators.
    
    Args:
        value: The value to convert (string, int, float, or None)
        default: Default value if conversion fails (default: 0.0)
    
    Returns:
        float: The converted value or default
    """
    if value is None:
        return default
    
    if isinstance(value, (int, float)):
        return float(value)
    
    if isinstance(value, str):
        # Remove commas and whitespace
        cleaned = value.replace(',', '').strip()
        
        if not cleaned or cleaned == '':
            return default
        
        try:
            return float(cleaned)
        except ValueError:
            print(f"Could not convert '{value}' to float, using default {default}")
            return default
    
    return default


if __name__ == "__main__":
    print("=" * 60)
    print("Testing safe_float_conversion()")
    print("=" * 60)
    
    test_cases = [
        ("1,000", 1000.0),
        ("1,000.50", 1000.50),
        ("10,000,000", 10000000.0),
        ("100", 100.0),
        ("100.50", 100.50),
        (1000, 1000.0),
        (1000.50, 1000.50),
        (None, 0.0),
        ("", 0.0),
        ("  ", 0.0),
        ("invalid", 0.0),
    ]
    
    print("\nRunning tests:")
    all_passed = True
    
    for value, expected in test_cases:
        result = safe_float_conversion(value)
        status = "PASS" if result == expected else "FAIL"
        print(f"[{status}] Input: {repr(value):20} | Expected: {expected:15} | Got: {result}")
        if result != expected:
            all_passed = False
    
    print("\n" + "=" * 60)
    if all_passed:
        print("ALL TESTS PASSED!")
    else:
        print("SOME TESTS FAILED!")
    print("=" * 60)
