#!/usr/bin/env python3
"""Test the You.com search integration."""

import os
import sys
from pathlib import Path

# Add the repo root to Python path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.web_search import youcom_web_search, WebSearchError


def test_youcom_basic_search():
    """Test basic You.com search functionality."""
    try:
        result = youcom_web_search("python programming", max_results=3)
        
        print(f"Query: {result.query}")
        print(f"Backend: {result.backend}")
        print(f"Model: {result.model}")
        print(f"Grounded: {result.grounded}")
        print(f"Results count: {len(result.results)}")
        print(f"Answer: {result.answer[:100]}...")
        print()
        
        for i, search_result in enumerate(result.results[:2]):
            print(f"Result {i+1}:")
            print(f"  Title: {search_result.title}")
            print(f"  URL: {search_result.url}")
            print(f"  Citable: {search_result.citable}")
            if search_result.supported_claims:
                print(f"  Snippet: {search_result.supported_claims[0][:100]}...")
            print()
            
        return True
        
    except WebSearchError as e:
        print(f"Search failed: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error: {e}")
        return False


def test_youcom_with_api_key():
    """Test You.com search with API key if available."""
    api_key = os.environ.get("YDC_API_KEY")
    if not api_key:
        print("YDC_API_KEY not set, skipping authenticated test")
        return True
        
    try:
        result = youcom_web_search(
            "artificial intelligence 2024", 
            api_key=api_key,
            max_results=5
        )
        
        print(f"Authenticated search results: {len(result.results)}")
        print(f"Grounded: {result.grounded}")
        return True
        
    except WebSearchError as e:
        print(f"Authenticated search failed: {e}")
        return False


def main():
    """Run You.com integration tests."""
    print("=== You.com Search Integration Tests ===")
    
    # Test basic keyless search
    print("Testing basic keyless search...")
    basic_ok = test_youcom_basic_search()
    
    # Test with API key if available
    print("Testing authenticated search...")
    auth_ok = test_youcom_with_api_key()
    
    if basic_ok and auth_ok:
        print("✅ All You.com integration tests passed!")
        return 0
    else:
        print("❌ Some You.com integration tests failed!")
        return 1


if __name__ == "__main__":
    sys.exit(main())