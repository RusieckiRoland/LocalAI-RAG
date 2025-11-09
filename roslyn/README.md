# 🧭 RoslynIndexer (moved)

This project has been **migrated into a separate repository** and moved to a new location:

👉 [https://github.com/RusieckiRoland/RoslynIndexer.git](https://github.com/RusieckiRoland/RoslynIndexer.git)

---

## 📦 About RoslynIndexer

**RoslynIndexer** is a high-performance, zero-build code indexer for .NET — it analyzes C# solutions and SQL projects, generating structured artifacts for Retrieval-Augmented Generation (RAG) systems.

The new repository contains the full source code, tests, and detailed technical documentation.

---

## 🚀 Quick Start

```bash
# 1. Clone the new repository
 git clone https://github.com/RusieckiRoland/RoslynIndexer.git
 cd RoslynIndexer

# 2. Run the indexer on any .NET solution
 dotnet run --project ./RoslynIndexer.Net9/RoslynIndexer.Net9.csproj -- \
   --solution "D:\Repo\src\MySolution.sln" \
   --temp-root "D:\Work\.idx"

# 3. Check the results
# → A ZIP archive will appear under .\.artifacts\index\
```

> 💡 **Note:** Before using the tool, make sure to read the `README.md` file in the new repository — it contains detailed setup instructions, configuration examples, and troubleshooting notes.

---

## 🛠️ Current Location

Main repository: **RusieckiRoland/RoslynIndexer**  
URL: [https://github.com/RusieckiRoland/RoslynIndexer.git](https://github.com/RusieckiRoland/RoslynIndexer.git)

Please use only the new repository — this one remains as a migration pointer.