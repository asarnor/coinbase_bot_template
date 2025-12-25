#!/usr/bin/env python3
"""
Test script to verify Coinbase API credentials format
This helps diagnose Railway 401 errors
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('COINBASE_API_KEY')
api_secret = os.getenv('COINBASE_API_SECRET')

print("=" * 70)
print("COINBASE API CREDENTIALS DIAGNOSTIC")
print("=" * 70)
print()

# Check if variables are set
if not api_key:
    print("❌ COINBASE_API_KEY is not set")
    sys.exit(1)
else:
    print(f"✅ COINBASE_API_KEY is set")
    print(f"   Length: {len(api_key)} characters")
    print(f"   Starts with: {api_key[:30]}...")
    print(f"   Format check: {'organizations/' in api_key or 'api_keys/' in api_key}")
    print()

if not api_secret:
    print("❌ COINBASE_API_SECRET is not set")
    sys.exit(1)
else:
    print(f"✅ COINBASE_API_SECRET is set")
    print(f"   Length: {len(api_secret)} characters")
    print(f"   Starts with: {api_secret[:50]}...")
    print(f"   Contains BEGIN: {'BEGIN EC PRIVATE KEY' in api_secret}")
    print(f"   Contains END: {'END EC PRIVATE KEY' in api_secret}")
    has_backslash_n = '\\n' in api_secret
    has_newline = '\n' in api_secret
    print(f"   Contains \\n: {has_backslash_n}")
    print(f"   Contains actual newlines: {has_newline}")
    print()

# Check secret format
if api_secret:
    if not api_secret.startswith('-----BEGIN EC PRIVATE KEY-----'):
        print("⚠️  WARNING: Secret doesn't start with '-----BEGIN EC PRIVATE KEY-----'")
        print("   This might be incorrect format")
        print()
    
    if '\\n' in api_secret:
        print("ℹ️  Secret contains \\n (literal backslash-n)")
        print("   This will be converted to actual newlines")
        print()
    
    if '\n' in api_secret:
        print("ℹ️  Secret contains actual newlines")
        print("   This is correct format")
        print()
    
    # Count newlines
    newline_count = api_secret.count('\n')
    backslash_n_count = api_secret.count('\\n')
    print(f"   Actual newlines found: {newline_count}")
    print(f"   \\n literals found: {backslash_n_count}")
    print()

# Test connection
print("=" * 70)
print("TESTING CONNECTION")
print("=" * 70)
print()

try:
    import ccxt
    
    # Process secret (convert \n to actual newlines)
    processed_secret = api_secret
    if '\\n' in processed_secret:
        processed_secret = processed_secret.replace('\\n', '\n')
    
    exchange = ccxt.coinbaseadvanced({
        'apiKey': api_key,
        'secret': processed_secret,
        'enableRateLimit': True,
        'sandbox': False,
    })
    
    print("🔌 Attempting to connect...")
    exchange.load_markets()
    print("✅ Connection successful!")
    print(f"   Loaded {len(exchange.markets)} markets")
    print()
    
    print("💰 Testing balance fetch...")
    balance = exchange.fetch_balance()
    print("✅ Balance fetch successful!")
    print(f"   Found {len([k for k, v in balance.items() if isinstance(v, dict) and v.get('total', 0) > 0])} currencies with balance")
    print()
    
    print("=" * 70)
    print("✅ ALL TESTS PASSED - Credentials are correct!")
    print("=" * 70)
    print()
    print("If Railway still shows 401 error:")
    print("1. Copy the EXACT secret shown above (with newlines)")
    print("2. In Railway, delete COINBASE_API_SECRET variable")
    print("3. Create it again and paste the complete secret")
    print("4. Make sure to click 'SHARE' on the variable")
    print("5. Redeploy")
    
except Exception as e:
    print(f"❌ Connection failed: {e}")
    print()
    print("=" * 70)
    print("TROUBLESHOOTING")
    print("=" * 70)
    print()
    
    error_msg = str(e).lower()
    
    if '401' in error_msg or 'unauthorized' in error_msg:
        print("401 Unauthorized - Authentication issue:")
        print("1. Verify API key has 'View' and 'Trade' permissions")
        print("2. Check secret is complete (not truncated)")
        print("3. Ensure secret format is correct")
        print("4. Try creating a new API key in Coinbase")
    elif 'invalid' in error_msg or 'format' in error_msg:
        print("Invalid format - Secret format issue:")
        print("1. Secret must start with '-----BEGIN EC PRIVATE KEY-----'")
        print("2. Secret must end with '-----END EC PRIVATE KEY-----'")
        print("3. If using \\n, ensure it's literal backslash-n")
    else:
        print(f"Error: {e}")
    
    sys.exit(1)

