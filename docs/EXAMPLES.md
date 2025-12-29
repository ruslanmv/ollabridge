# 📚 OllaBridge Examples

**Real-world code examples for common use cases**

---

## Table of Contents

- [Basic Chat](#basic-chat)
- [Streaming Responses](#streaming-responses-coming-soon)
- [Embeddings & Vector Search](#embeddings--vector-search)
- [LangChain Integration](#langchain-integration)
- [Multi-Node Setup](#multi-node-setup)
- [Using with Different Languages](#using-with-different-languages)
- [Production Deployment](#production-deployment)

---

## Basic Chat

### Simple Question-Answer

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[
        {"role": "user", "content": "What is the capital of France?"}
    ]
)

print(response.choices[0].message.content)
# Output: "The capital of France is Paris."
```

### Conversation with Context

```python
messages = [
    {"role": "system", "content": "You are a helpful Python tutor."},
    {"role": "user", "content": "What is a list?"},
]

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=messages
)

# Add AI's response to conversation
messages.append({
    "role": "assistant",
    "content": response.choices[0].message.content
})

# Continue conversation
messages.append({
    "role": "user",
    "content": "Can you show me an example?"
})

response = client.chat.completions.create(
    model="deepseek-r1",
    messages=messages
)

print(response.choices[0].message.content)
```

### Temperature Control (Creativity)

```python
# More creative (higher temperature)
creative = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Write a tagline for a coffee shop"}],
    temperature=1.0  # Range: 0.0 (focused) to 2.0 (creative)
)

# More focused (lower temperature)
focused = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "What is 2+2?"}],
    temperature=0.1
)
```

---

## Streaming Responses (Coming Soon)

*This feature is planned for a future release*

```python
# Future API:
for chunk in client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Count to 10"}],
    stream=True
):
    print(chunk.choices[0].delta.content, end="")
```

---

## Embeddings & Vector Search

### Generate Embeddings

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

# Single text
result = client.embeddings.create(
    model="nomic-embed-text",
    input="Hello, world!"
)

vector = result.data[0].embedding
print(f"Vector dimension: {len(vector)}")
# Output: Vector dimension: 768
```

### Build a Simple RAG System

```python
import numpy as np
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

# Your knowledge base
docs = [
    "Paris is the capital of France.",
    "London is the capital of the United Kingdom.",
    "Berlin is the capital of Germany.",
]

# Generate embeddings for all documents
doc_embeddings = []
for doc in docs:
    result = client.embeddings.create(
        model="nomic-embed-text",
        input=doc
    )
    doc_embeddings.append(result.data[0].embedding)

# User query
query = "What is the capital of France?"
query_result = client.embeddings.create(
    model="nomic-embed-text",
    input=query
)
query_embedding = query_result.data[0].embedding

# Find most similar document (cosine similarity)
similarities = [
    np.dot(query_embedding, doc_emb) /
    (np.linalg.norm(query_embedding) * np.linalg.norm(doc_emb))
    for doc_emb in doc_embeddings
]

best_match_idx = np.argmax(similarities)
context = docs[best_match_idx]

# Generate answer with context
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[
        {"role": "system", "content": f"Context: {context}"},
        {"role": "user", "content": query}
    ]
)

print(response.choices[0].message.content)
```

---

## LangChain Integration

### Basic Chat

```python
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage

llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key",
    model="deepseek-r1",
    temperature=0.7
)

messages = [
    SystemMessage(content="You are a helpful assistant."),
    HumanMessage(content="Explain async/await in Python")
]

response = llm.invoke(messages)
print(response.content)
```

### Chains

```python
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain

llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key",
    model="deepseek-r1"
)

prompt = ChatPromptTemplate.from_template(
    "Write a {adjective} poem about {topic}"
)

chain = LLMChain(llm=llm, prompt=prompt)

result = chain.run(adjective="funny", topic="programming")
print(result)
```

### RAG with LangChain

```python
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import FAISS
from langchain.chains import RetrievalQA

# Set up LLM and embeddings
llm = ChatOpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key",
    model="deepseek-r1"
)

embeddings = OpenAIEmbeddings(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key",
    model="nomic-embed-text"
)

# Load and split documents
documents = [
    "OllaBridge is an OpenAI-compatible gateway for local LLMs.",
    "You can add remote GPUs by running ollabridge-node join.",
    "The default port is 11435.",
]

text_splitter = RecursiveCharacterTextSplitter(chunk_size=100)
texts = text_splitter.create_documents(documents)

# Create vector store
vectorstore = FAISS.from_documents(texts, embeddings)

# Create RAG chain
qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    retriever=vectorstore.as_retriever()
)

# Ask questions
answer = qa_chain.run("How do I add a remote GPU?")
print(answer)
```

---

## Multi-Node Setup

### Scenario: Local + Cloud GPU

```python
from openai import OpenAI

# Your gateway automatically load-balances across:
# - Your local laptop (node 1)
# - Your gaming PC (node 2)
# - A Colab GPU (node 3)

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

# This request goes to whichever node is available
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "Hello!"}]
)

print(response.choices[0].message.content)
```

### Check Which Nodes Are Connected

```python
import httpx

response = httpx.get(
    "http://localhost:11435/admin/runtimes",
    headers={"X-API-Key": "your-api-key"}
)

runtimes = response.json()["runtimes"]

for runtime in runtimes:
    print(f"Node: {runtime['node_id']}")
    print(f"  Connector: {runtime['connector']}")
    print(f"  Healthy: {runtime['healthy']}")
    print(f"  Models: {', '.join(runtime['models'])}")
    print()
```

---

## Using with Different Languages

### Node.js / TypeScript

```typescript
import OpenAI from "openai";

const client = new OpenAI({
  baseURL: "http://localhost:11435/v1",
  apiKey: process.env.OLLABRIDGE_KEY,
});

async function chat(prompt: string): Promise<string> {
  const completion = await client.chat.completions.create({
    model: "deepseek-r1",
    messages: [{ role: "user", content: prompt }],
  });

  return completion.choices[0].message.content;
}

// Usage
const answer = await chat("What is TypeScript?");
console.log(answer);
```

### JavaScript (Browser)

```javascript
// Using fetch API
async function askAI(question) {
  const response = await fetch("http://localhost:11435/v1/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": "Bearer your-api-key"
    },
    body: JSON.stringify({
      model: "deepseek-r1",
      messages: [{ role: "user", content: question }]
    })
  });

  const data = await response.json();
  return data.choices[0].message.content;
}

askAI("What is JavaScript?").then(console.log);
```

### Go

```go
package main

import (
    "context"
    "fmt"
    openai "github.com/sashabaranov/go-openai"
)

func main() {
    config := openai.DefaultConfig("your-api-key")
    config.BaseURL = "http://localhost:11435/v1"
    client := openai.NewClientWithConfig(config)

    resp, err := client.CreateChatCompletion(
        context.Background(),
        openai.ChatCompletionRequest{
            Model: "deepseek-r1",
            Messages: []openai.ChatCompletionMessage{
                {
                    Role:    openai.ChatMessageRoleUser,
                    Content: "Hello!",
                },
            },
        },
    )

    if err != nil {
        panic(err)
    }

    fmt.Println(resp.Choices[0].Message.Content)
}
```

### Rust

```rust
use reqwest;
use serde_json::json;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = reqwest::Client::new();

    let response = client
        .post("http://localhost:11435/v1/chat/completions")
        .header("Authorization", "Bearer your-api-key")
        .json(&json!({
            "model": "deepseek-r1",
            "messages": [
                {"role": "user", "content": "Hello!"}
            ]
        }))
        .send()
        .await?
        .json::<serde_json::Value>()
        .await?;

    println!("{}", response["choices"][0]["message"]["content"]);
    Ok(())
}
```

---

## Production Deployment

### Using Environment Variables

```python
import os
from openai import OpenAI

client = OpenAI(
    base_url=os.getenv("OLLABRIDGE_BASE_URL", "http://localhost:11435/v1"),
    api_key=os.getenv("OLLABRIDGE_API_KEY")
)

response = client.chat.completions.create(
    model=os.getenv("OLLABRIDGE_MODEL", "deepseek-r1"),
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**.env file:**
```env
OLLABRIDGE_BASE_URL=https://your-gateway.com/v1
OLLABRIDGE_API_KEY=sk-ollabridge-production-key
OLLABRIDGE_MODEL=deepseek-r1
```

### Error Handling

```python
from openai import OpenAI
import httpx

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

try:
    response = client.chat.completions.create(
        model="deepseek-r1",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.choices[0].message.content)

except httpx.HTTPStatusError as e:
    print(f"HTTP error: {e.response.status_code}")
    print(f"Response: {e.response.text}")

except httpx.ConnectError:
    print("Cannot connect to OllaBridge. Is it running?")

except Exception as e:
    print(f"Unexpected error: {e}")
```

### Retry Logic

```python
from openai import OpenAI
from tenacity import retry, wait_exponential, stop_after_attempt

client = OpenAI(
    base_url="http://localhost:11435/v1",
    api_key="your-api-key"
)

@retry(
    wait=wait_exponential(min=1, max=10),
    stop=stop_after_attempt(3)
)
def ask_with_retry(question: str) -> str:
    response = client.chat.completions.create(
        model="deepseek-r1",
        messages=[{"role": "user", "content": question}]
    )
    return response.choices[0].message.content

# Will retry up to 3 times with exponential backoff
answer = ask_with_retry("What is AI?")
print(answer)
```

---

## Need More Examples?

- 📖 [LangChain Documentation](https://python.langchain.com/)
- 🔗 [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- 💬 [Ask in Discussions](https://github.com/ruslanmv/ollabridge/discussions)

---

**Next:** Check out [ARCHITECTURE.md](ARCHITECTURE.md) to understand how OllaBridge works under the hood.
