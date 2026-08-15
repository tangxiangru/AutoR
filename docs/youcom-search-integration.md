# You.com Search Integration

AutoR now supports You.com Search API as an optional web search provider alongside the existing Gemini integration. This provides an alternative search backend that can be useful when Gemini credentials are not available or when you prefer You.com's search results.

## Setup

### Environment Variables

```bash
# Optional: You.com API key for enhanced results and higher rate limits
export YDC_API_KEY="your-you-com-api-key"

# Optional: Force You.com as the search backend
export AUTOR_WEB_SEARCH_BACKEND="youcom"
```

**Note**: You.com API supports keyless access with reasonable rate limits. An API key is optional but recommended for production use to get higher rate limits and better performance.

### Command Line Usage

```bash
# Use You.com search explicitly
python3 tools/web_search.py "machine learning trends 2024" --provider youcom

# Use auto-selection (falls back to Gemini if You.com fails)
python3 tools/web_search.py "quantum computing advances" --provider auto

# JSON output with You.com
python3 tools/web_search.py "AI safety research" --provider youcom --json
```

## API Response Format

You.com search returns results in the same `WebSearchResponse` format as Gemini:

```json
{
  "query": "machine learning trends 2024",
  "model": "youcom-search-api", 
  "backend": "youcom",
  "answer": "Summary based on search snippets...",
  "grounded": true,
  "citable_source_count": 5,
  "results": [
    {
      "title": "Machine Learning Trends in 2024",
      "url": "https://example.com/ml-trends",
      "citable": true,
      "supported_claims": ["Snippet from the search result..."]
    }
  ]
}
```

## Integration Architecture

The You.com integration follows the same pattern as the existing Gemini backend:

- **Optional Provider**: You.com can be selected via `--provider youcom` or `AUTOR_WEB_SEARCH_BACKEND=youcom`
- **Fallback Support**: Auto-selection prefers available Gemini credentials, falls back to You.com keyless access
- **Same Interface**: Returns `WebSearchResponse` objects compatible with existing AutoR workflows
- **Error Handling**: Graceful failure with descriptive error messages

## Provider Selection Priority

1. **Explicit Selection**: `--provider youcom` or `--provider gemini` forces that backend
2. **Environment Override**: `AUTOR_WEB_SEARCH_BACKEND=youcom` sets the default
3. **Auto Selection**: Falls back in order:
   - Gemini API key (if available)
   - Vertex AI credentials (if available)
   - You.com keyless access (always available)

## Configuration Options

### You.com Specific

- `YDC_API_KEY`: Optional API key for enhanced performance
- `YOUCOM_BASE_URL`: Optional custom API base URL (default: `https://api.you.com`)

### Existing Gemini Options

All existing Gemini configuration remains unchanged:

- `GOOGLE_API_KEY` / `GEMINI_API_KEY`: Gemini API credentials
- `AUTOR_VERTEX_PROJECT`: Vertex AI project
- `AUTOR_WEB_SEARCH_MODEL`: Gemini model selection

## Error Handling

Common You.com integration errors and solutions:

- **401 Unauthorized**: Invalid `YDC_API_KEY` - check your API key or remove it for keyless access
- **429 Rate Limited**: You.com rate limits exceeded - add `YDC_API_KEY` for higher limits or retry later  
- **Network errors**: Connectivity issues - check internet connection and firewall settings

## Usage in AutoR Workflows

The You.com integration is fully compatible with existing AutoR search workflows:

```python
# Both backends return the same WebSearchResponse format
response = youcom_web_search("AI research trends")
response = gemini_web_search("AI research trends")

# Same fields available
print(response.query)
print(response.answer) 
print(response.grounded)
for result in response.results:
    print(f"{result.title}: {result.url}")
```

## Performance Considerations

- **You.com**: Generally faster response times, good international coverage
- **Gemini**: Better answer synthesis, Google-quality search results
- **Keyless vs API Key**: You.com keyless access has lower rate limits than authenticated requests

Choose the provider based on your specific needs for answer quality, response time, and rate limit requirements.