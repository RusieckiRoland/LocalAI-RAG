# .NET indexing and branch preparation

## To index your .NET solution

```bash
# 1. Clone the indexer
git clone https://github.com/RusieckiRoland/RoslynIndexer.git
cd RoslynIndexer

# 2. Run the indexer (see full README in that repo)
dotnet run --project ./RoslynIndexer.Net9/RoslynIndexer.Net9.csproj -- \
  --solution "D:\Repo\src\MySolution.sln" \
  --temp-root "D:\Work\"
```

**PowerShell**

``` PowerShell
git clone https://github.com/RusieckiRoland/RoslynIndexer.git
cd RoslynIndexer
dotnet run --project .\RoslynIndexer.Net9\RoslynIndexer.Net9.csproj -- `
  --solution "D:\Repo\src\MySolution.sln" `
  --temp-root "D:\Work\"
```

---

## Branch preparation guide

1. Create the `branches/` folder at the repository root (used for exported branch bundles and artifacts).

2. Follow the instructions in **[`HOW_TO_PREPARE_REPO.md`](../../HOW_TO_PREPARE_REPO.md)** located in the repository root. It explains how to index the repository and then build the retrieval store in Weaviate (BYOV) from the generated chunks.
