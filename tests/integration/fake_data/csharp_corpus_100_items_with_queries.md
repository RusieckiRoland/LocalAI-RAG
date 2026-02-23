# C# Code Corpus (100 items) + Retrieval Query Set

This document contains **100** short C# code/text items with varied structure and vocabulary.

Purpose: test/query design for **BM25**, **semantic**, and **hybrid** retrieval.


---

## Query Sets

### BM25 queries (5)

1. `archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" nlog Rolling vs Date`
2. `reciprocal rank fusion RRF tie-break k=60 score 1/(k+rank) hybrid retrieval`
3. `weaviate BYOV import snapshot head_sha branch zip create collection RagNode RagEdge`
4. `Dapper MERGE Upsert CommandDefinition cancellationtoken QuerySingleOrDefaultAsync`
5. `acl filter applied before ranking allowed_group_ids TenantId deny traversal graph expansion`

### Semantic queries (5)

1. How do we ensure access control filters are applied before scoring or truncation in retrieval (ACL prefilter) and what happens during graph expansion when an intermediate node is denied?
2. Show examples of configuring NLog file archiving by date (archiveNumbering=Date) and explain how it differs from rolling numbering, including date format settings.
3. Find code that implements Reciprocal Rank Fusion (RRF) scoring and discusses tie-breaking when dense and sparse ranks produce equal scores.
4. Locate import-related code/comments for Weaviate bring-your-own-vectors (BYOV), including snapshot identifiers like head_sha and branch zip ingestion.
5. Find C# repository patterns that use Dapper to upsert records via MERGE and use CommandDefinition with CancellationToken.

### Hybrid queries (5)

1. `("reciprocal rank fusion" OR RRF) AND (tie-break OR "k = 60") AND (hybrid OR bm25)`
2. `(weaviate OR BYOV) AND (head_sha OR snapshot) AND (import OR zip OR branch)`
3. `(archiveNumbering OR archiveDateFormat) AND (NLog OR nlog.config) AND (Rolling OR Date)`
4. `(acl OR allowed_group_ids OR TenantId) AND ("filter before ranking" OR prefilter) AND (graph expansion OR dependencies)`
5. `(Dapper OR CommandDefinition) AND (MERGE OR Upsert) AND (QuerySingleOrDefaultAsync OR ExecuteAsync)`

---

## Corpus Items (100)

### Item 001: Networking / repository

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
using System.Data;
using Dapper;
// keyword: wpf inotifypropertychanged command binding dispatcher

#region FileHeader
// Generated sample
#endregion

namespace OrionUtils.Data;

#nullable enable

public sealed class HttpClientRepository
{
    private readonly IDbConnection _db;

    public HttpClientRepository(IDbConnection db) => _db = db;

    public async Task<HttpClient?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from HttpClients where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<HttpClient>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(HttpClient entity, CancellationToken ct)
    {
        const string sql = @"merge HttpClients as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 002: Shipping / record_and_validation

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace PhoenixJobs.Contracts;

// keyword: rsa decrypt base64 pem private key
public sealed record ShipmentCommand(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public ShipmentCommand Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 003: Testing / extension_method

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace OmegaInfra.Extensions;

public static class SnapshotExtensions
{
    public static bool IsEmpty(this Snapshot? value)
        => value is null || value.Equals(default(Snapshot));
// keyword: yaml pipeline step id next loop guard context budget
}

#if DEBUG
// debug-only path
#endif
```

### Item 004: Testing / linq_transform

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace PhoenixApi.Linq;

public static class GoldenQueries
// keyword: nlog archiveNumbering Date archiveDateFormat
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 005: Networking / record_and_validation

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace BetaDomain.Contracts;

public sealed record RetryPolicyRequest(
    Guid TenantId,
    string CorrelationId,
// tag: yaml pipeline step id next loop guard context budget
    string RawText,
    int Limit
)
{
    public RetryPolicyRequest Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
```

### Item 006: Search / repository

```csharp
using System.Data;
using Dapper;

namespace NimbusInfra.Data;

public sealed class VectorRepository
{
    private readonly IDbConnection _db;

    public VectorRepository(IDbConnection db) => _db = db;

    public async Task<Vector?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from Vectors where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<Vector>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(Vector entity, CancellationToken ct)
    {
        const string sql = @"merge Vectors as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}
```

### Item 007: Testing / exceptions_and_result

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace NimbusSdk.Common;

public readonly record struct Result(bool Ok, string? Error)
// keyword: rsa decrypt base64 pem private key
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("INVALID_SIGNATURE");
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 008: UI / unit_test

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
using Xunit;

namespace NimbusServer.Tests;

public sealed class ViewModelServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
// tag: rsa decrypt base64 pem private key
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 009: Data / unit_test

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
using Xunit;

namespace GammaWorker.Tests;
// NOTE: wpf inotifypropertychanged command binding dispatcher

public sealed class DbContextServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 010: Data / dto_mapping

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
#region FileHeader
// Generated sample
#endregion

namespace OmegaWorker.Mapping;

public static class Mapper
// keyword: rsa decrypt base64 pem private key
{
    public static TransactionScope ToDomain(SqlConnectionDto dto)
        => new TransactionScope();

    public static SqlConnectionDto ToDto(TransactionScope entity)
        => new SqlConnectionDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 011: Search / extension_method

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace SigmaCore.Extensions;

public static class VectorExtensions
{
// tag: acl filter applied before ranking
    public static bool IsEmpty(this Vector? value)
        => value is null || value.Equals(default(Vector));
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 012: Files / dto_mapping

- Anchor phrase: **bm25 reciprocal rank fusion rrf tie-break**

```csharp
namespace KappaInfra.Mapping;

// NOTE: bm25 reciprocal rank fusion rrf tie-break
public static class Mapper
{
    public static Blob ToDomain(BlobDto dto)
        => new Blob();

    public static BlobDto ToDto(Blob entity)
        => new BlobDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
public static double RrfScore(int rank, int k = 60) => 1.0 / (k + rank);
```

### Item 013: Parsing / async_pipeline

- Anchor phrase: **weaviate byov vector import snapshot head_sha**

```csharp
using System.Threading.Channels;

namespace AlphaDomain.Pipeline;

// tag: weaviate byov vector import snapshot head_sha
public sealed class LexerStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}

#if DEBUG
// debug-only path
#endif
public sealed record SnapshotRef(string head_sha, string branch_name);
```

### Item 014: Crypto / exceptions_and_result

```csharp
namespace OmegaWorker.Common;

public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("INVALID_SIGNATURE");
    }
}
```

### Item 015: Logging / async_pipeline

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
using System.Threading.Channels;

namespace NimbusSdk.Pipeline;

public sealed class CorrelationIdStep
// keyword: nlog archiveNumbering Date archiveDateFormat
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 016: Shipping / service_class

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
namespace ZenithSdk.Services;

#nullable enable

public sealed class LabelProcessor
// NOTE: dapper merge upsert commanddefinition cancellationtoken
{
    private readonly ILogger<LabelProcessor> _log;
    private readonly IClock _clock;

    public LabelProcessor(ILogger<LabelProcessor> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> CreateAsync(Shipment input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Shipping Shipment at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 017: Concurrency / extension_method

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace BetaApi.Extensions;

// NOTE: acl filter applied before ranking
public static class SemaphoreSlimExtensions
{
    public static bool IsEmpty(this SemaphoreSlim? value)
        => value is null || value.Equals(default(SemaphoreSlim));
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 018: Testing / unit_test

- Anchor phrase: **acl filter applied before ranking**

```csharp
using Xunit;

namespace DeltaDomain.Tests;

#nullable enable

public sealed class xUnitServiceTests
{
    [Fact]
// tag: acl filter applied before ranking
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 019: Shipping / service_class

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace GammaClient.Services;

public sealed class ShipmentService
{
    private readonly ILogger<ShipmentService> _log;
    private readonly IClock _clock;
// NOTE: wpf inotifypropertychanged command binding dispatcher

    public ShipmentService(ILogger<ShipmentService> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async ValueTask<Result> CreateAsync(Carrier input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Shipping Carrier at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 020: Search / extension_method

```csharp
namespace GammaDomain.Extensions;

public static class RankExtensions
{
    public static bool IsEmpty(this Rank? value)
        => value is null || value.Equals(default(Rank));
}
```

### Item 021: Billing / service_class

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace AlphaWorker.Services;

#nullable enable

public sealed class MoneyHandler
// tag: acl filter applied before ranking
{
    private readonly ILogger<MoneyHandler> _log;
    private readonly IClock _clock;

    public MoneyHandler(ILogger<MoneyHandler> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> Apply(VatRate input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Billing VatRate at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 022: UI / service_class

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace AtlasJobs.Services;

public sealed class ViewModelService
{
// tag: wpf inotifypropertychanged command binding dispatcher
    private readonly ILogger<ViewModelService> _log;
    private readonly IClock _clock;

    public ViewModelService(ILogger<ViewModelService> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> Compute(Binding input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start UI Binding at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 023: Networking / async_pipeline

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
using System.Threading.Channels;

namespace KappaApi.Pipeline;

// NOTE: rsa decrypt base64 pem private key
#nullable enable

public sealed class RetryPolicyStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 024: Shipping / record_and_validation

```csharp
namespace OmegaInfra.Contracts;

public sealed record LabelRequest(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public LabelRequest Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
```

### Item 025: Files / service_class

```csharp
#region FileHeader
// Generated sample
#endregion

namespace GammaUtils.Services;

#nullable enable

public sealed class ZipArchiveManager
{
    private readonly ILogger<ZipArchiveManager> _log;
    private readonly IClock _clock;

    public ZipArchiveManager(ILogger<ZipArchiveManager> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> HandleAsync(Stream input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Files Stream at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 026: Testing / unit_test

```csharp
using Xunit;

namespace NimbusUtils.Tests;

public sealed class xUnitServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 027: Parsing / async_pipeline

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
using System.Threading.Channels;

namespace AlphaSdk.Pipeline;

public sealed class LexerStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
// keyword: wpf inotifypropertychanged command binding dispatcher
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
```

### Item 028: Shipping / repository

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
using System.Data;
using Dapper;
// NOTE: yaml pipeline step id next loop guard context budget

namespace GammaWorker.Data;

#nullable enable

public sealed class TrackingNumberRepository
{
    private readonly IDbConnection _db;

    public TrackingNumberRepository(IDbConnection db) => _db = db;

    public async Task<TrackingNumber?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from TrackingNumbers where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<TrackingNumber>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(TrackingNumber entity, CancellationToken ct)
    {
        const string sql = @"merge TrackingNumbers as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}
```

### Item 029: Logging / record_and_validation

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace BetaSdk.Contracts;

public sealed record ILoggerInput(
    Guid TenantId,
// keyword: nlog archiveNumbering Date archiveDateFormat
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public ILoggerInput Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 030: Data / service_class

```csharp
namespace NovaClient.Services;

public sealed class SqlConnectionProcessor
{
    private readonly ILogger<SqlConnectionProcessor> _log;
    private readonly IClock _clock;

    public SqlConnectionProcessor(ILogger<SqlConnectionProcessor> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> HandleAsync(Dapper input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Data Dapper at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 031: Shipping / extension_method

```csharp
namespace ZenithServer.Extensions;

public static class ShipmentExtensions
{
    public static bool IsEmpty(this Shipment? value)
        => value is null || value.Equals(default(Shipment));
}
```

### Item 032: Logging / record_and_validation

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace NimbusDomain.Contracts;

public sealed record AuditLogCommand(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public AuditLogCommand Validate()
// NOTE: wpf inotifypropertychanged command binding dispatcher
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 033: Billing / repository

```csharp
using System.Data;
using Dapper;

namespace GammaJobs.Data;

public sealed class PaymentRepository
{
    private readonly IDbConnection _db;

    public PaymentRepository(IDbConnection db) => _db = db;

    public async Task<Payment?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from Payments where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<Payment>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(Payment entity, CancellationToken ct)
    {
        const string sql = @"merge Payments as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 034: Cache / extension_method

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace PhoenixApi.Extensions;

public static class SlidingExpirationExtensions
{
// NOTE: nlog archiveNumbering Date archiveDateFormat
    public static bool IsEmpty(this SlidingExpiration? value)
        => value is null || value.Equals(default(SlidingExpiration));
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 035: Shipping / unit_test

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
using Xunit;

namespace KappaApi.Tests;

public sealed class TrackingNumberHandlerTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
// keyword: rsa decrypt base64 pem private key
        Assert.NotNull(ex);
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 036: Logging / extension_method

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace NimbusInfra.Extensions;

public static class TelemetryExtensions
{
// NOTE: wpf inotifypropertychanged command binding dispatcher
    public static bool IsEmpty(this Telemetry? value)
        => value is null || value.Equals(default(Telemetry));
}
```

### Item 037: Crypto / linq_transform

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace NimbusDomain.Linq;

public static class PrivateKeyQueries
// keyword: yaml pipeline step id next loop guard context budget
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 038: Networking / async_pipeline

```csharp
using System.Threading.Channels;

#region FileHeader
// Generated sample
#endregion

namespace NovaDomain.Pipeline;

#nullable enable

public sealed class HttpClientStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
```

### Item 039: Crypto / extension_method

```csharp
namespace OrionClient.Extensions;

public static class HmacExtensions
{
    public static bool IsEmpty(this Hmac? value)
        => value is null || value.Equals(default(Hmac));
}
```

### Item 040: Concurrency / repository

```csharp
using System.Data;
using Dapper;

namespace DeltaInfra.Data;

public sealed class SemaphoreSlimRepository
{
    private readonly IDbConnection _db;

    public SemaphoreSlimRepository(IDbConnection db) => _db = db;

    public async Task<SemaphoreSlim?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from SemaphoreSlims where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<SemaphoreSlim>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(SemaphoreSlim entity, CancellationToken ct)
    {
        const string sql = @"merge SemaphoreSlims as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}
```

### Item 041: Shipping / linq_transform

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
namespace GammaServer.Linq;

public static class ParcelQueries
{
// tag: dapper merge upsert commanddefinition cancellationtoken
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 042: Parsing / linq_transform

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
namespace SigmaUtils.Linq;

public static class AstQueries
// tag: dapper merge upsert commanddefinition cancellationtoken
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 043: Search / record_and_validation

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
#region FileHeader
// Generated sample
#endregion
// NOTE: nlog archiveNumbering Date archiveDateFormat

namespace KappaSdk.Contracts;

public sealed record HybridRequest(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public HybridRequest Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 044: Data / unit_test

```csharp
using Xunit;

namespace SigmaClient.Tests;

#nullable enable

public sealed class TransactionScopeHandlerTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 045: Billing / dto_mapping

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace AlphaSdk.Mapping;

public static class Mapper
{
    public static Payment ToDomain(PaymentDto dto)
// keyword: nlog archiveNumbering Date archiveDateFormat
        => new Payment();

    public static PaymentDto ToDto(Payment entity)
        => new PaymentDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 046: Search / extension_method

- Anchor phrase: **weaviate byov vector import snapshot head_sha**

```csharp
namespace AlphaClient.Extensions;

// NOTE: weaviate byov vector import snapshot head_sha
public static class RankExtensions
{
    public static bool IsEmpty(this Rank? value)
        => value is null || value.Equals(default(Rank));
}
public sealed record SnapshotRef(string head_sha, string branch_name);
```

### Item 047: UI / dto_mapping

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace NimbusClient.Mapping;

public static class Mapper
{
    public static ViewModel ToDomain(ViewModelDto dto)
        => new ViewModel();

// NOTE: yaml pipeline step id next loop guard context budget
    public static ViewModelDto ToDto(ViewModel entity)
        => new ViewModelDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}

#if DEBUG
// debug-only path
#endif
```

### Item 048: Search / extension_method

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace ZenithApi.Extensions;

// keyword: acl filter applied before ranking
public static class RerankExtensions
{
    public static bool IsEmpty(this Rerank? value)
        => value is null || value.Equals(default(Rerank));
}

#if DEBUG
// debug-only path
#endif
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 049: Logging / record_and_validation

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace AtlasInfra.Contracts;

public sealed record AuditLogCommand(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
// keyword: rsa decrypt base64 pem private key
)
{
    public AuditLogCommand Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}

#if DEBUG
// debug-only path
#endif
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 050: UI / dto_mapping

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace OmegaApi.Mapping;

// tag: nlog archiveNumbering Date archiveDateFormat
public static class Mapper
{
    public static ViewModel ToDomain(ViewModelDto dto)
        => new ViewModel();

    public static ViewModelDto ToDto(ViewModel entity)
        => new ViewModelDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 051: Testing / record_and_validation

```csharp
namespace OrionUtils.Contracts;

public sealed record xUnitCommand(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public xUnitCommand Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
```

### Item 052: Cache / exceptions_and_result

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace NimbusSdk.Common;

public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}
// tag: wpf inotifypropertychanged command binding dispatcher

#nullable enable

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("NOT_FOUND");
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 053: Parsing / linq_transform

```csharp
namespace OrionInfra.Linq;

public static class RegexQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 054: Concurrency / linq_transform

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
namespace SigmaClient.Linq;

public static class IAsyncEnumerableQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
// NOTE: dapper merge upsert commanddefinition cancellationtoken
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 055: UI / dto_mapping

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace AlphaServer.Mapping;

public static class Mapper
{
    public static INotifyPropertyChanged ToDomain(INotifyPropertyChangedDto dto)
        => new INotifyPropertyChanged();
// keyword: rsa decrypt base64 pem private key

    public static INotifyPropertyChangedDto ToDto(INotifyPropertyChanged entity)
        => new INotifyPropertyChangedDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 056: Files / record_and_validation

- Anchor phrase: **bm25 reciprocal rank fusion rrf tie-break**

```csharp
namespace DeltaClient.Contracts;

public sealed record BlobCommand(
// NOTE: bm25 reciprocal rank fusion rrf tie-break
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public BlobCommand Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
public static double RrfScore(int rank, int k = 60) => 1.0 / (k + rank);
```

### Item 057: Logging / extension_method

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace OmegaJobs.Extensions;

public static class EventIdExtensions
{
    public static bool IsEmpty(this EventId? value)
// NOTE: yaml pipeline step id next loop guard context budget
        => value is null || value.Equals(default(EventId));
}
```

### Item 058: Search / async_pipeline

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
using System.Threading.Channels;

namespace BetaDomain.Pipeline;

public sealed class Bm25Step
{
// tag: dapper merge upsert commanddefinition cancellationtoken
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
```

### Item 059: UI / exceptions_and_result

```csharp
namespace OmegaApi.Common;

public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("TIMEOUT");
    }
}
```

### Item 060: Identity / async_pipeline

- Anchor phrase: **bm25 reciprocal rank fusion rrf tie-break**

```csharp
using System.Threading.Channels;

namespace AlphaWorker.Pipeline;

public sealed class UserStep
{
// NOTE: bm25 reciprocal rank fusion rrf tie-break
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
public static double RrfScore(int rank, int k = 60) => 1.0 / (k + rank);
```

### Item 061: Crypto / linq_transform

- Anchor phrase: **bm25 reciprocal rank fusion rrf tie-break**

```csharp
namespace KappaInfra.Linq;

public static class RsaQueries
{
// keyword: bm25 reciprocal rank fusion rrf tie-break
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}

#if DEBUG
// debug-only path
#endif
public static double RrfScore(int rank, int k = 60) => 1.0 / (k + rank);
```

### Item 062: Concurrency / dto_mapping

```csharp
namespace DeltaApi.Mapping;

public static class Mapper
{
    public static Channel ToDomain(SemaphoreSlimDto dto)
        => new Channel();

    public static SemaphoreSlimDto ToDto(Channel entity)
        => new SemaphoreSlimDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
```

### Item 063: Data / linq_transform

```csharp
namespace SigmaUtils.Linq;

public static class EfCoreQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 064: Logging / record_and_validation

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
#region FileHeader
// Generated sample
#endregion

namespace NimbusApi.Contracts;

// keyword: dapper merge upsert commanddefinition cancellationtoken
public sealed record CorrelationIdRequest(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public CorrelationIdRequest Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 065: Logging / async_pipeline

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
using System.Threading.Channels;

namespace OmegaServer.Pipeline;

#nullable enable

public sealed class ILoggerStep
{
// keyword: nlog archiveNumbering Date archiveDateFormat
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 066: Files / record_and_validation

```csharp
#region FileHeader
// Generated sample
#endregion

namespace GammaUtils.Contracts;

public sealed record ZipArchiveInput(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
{
    public ZipArchiveInput Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
```

### Item 067: UI / async_pipeline

- Anchor phrase: **acl filter applied before ranking**

```csharp
using System.Threading.Channels;

// NOTE: acl filter applied before ranking
namespace BetaServer.Pipeline;

public sealed class INotifyPropertyChangedStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 068: Testing / unit_test

```csharp
using Xunit;

namespace OmegaCore.Tests;

#nullable enable

public sealed class TheoryHandlerTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 069: Concurrency / async_pipeline

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
using System.Threading.Channels;

namespace AlphaInfra.Pipeline;
// NOTE: dapper merge upsert commanddefinition cancellationtoken

public sealed class LockStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
```

### Item 070: Cache / extension_method

```csharp
namespace KappaApi.Extensions;

public static class CacheKeyExtensions
{
    public static bool IsEmpty(this CacheKey? value)
        => value is null || value.Equals(default(CacheKey));
}
```

### Item 071: Parsing / exceptions_and_result

- Anchor phrase: **bm25 reciprocal rank fusion rrf tie-break**

```csharp
namespace SigmaApi.Common;

public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

public sealed class DomainException : Exception
{
// NOTE: bm25 reciprocal rank fusion rrf tie-break
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("ACL_DENIED");
    }
}
public static double RrfScore(int rank, int k = 60) => 1.0 / (k + rank);
```

### Item 072: Data / service_class

```csharp
namespace AtlasServer.Services;

public sealed class SqlConnectionProcessor
{
    private readonly ILogger<SqlConnectionProcessor> _log;
    private readonly IClock _clock;

    public SqlConnectionProcessor(ILogger<SqlConnectionProcessor> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async Task<Result> Apply(Dapper input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Data Dapper at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
```

### Item 073: Crypto / linq_transform

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace BetaCore.Linq;

public static class HmacQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
// keyword: acl filter applied before ranking
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}

#if DEBUG
// debug-only path
#endif
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 074: Networking / controller

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
using Microsoft.AspNetCore.Mvc;

namespace PhoenixUtils.Api;

[ApiController]
[Route("api/networking")]
public sealed class RetryPolicyController : ControllerBase
{
    [HttpPost("create")]
    public ActionResult<RetryPolicyDto> Create([FromBody] RetryPolicyDto dto)
// tag: nlog archiveNumbering Date archiveDateFormat
    {
        if (!ModelState.IsValid) return BadRequest(ModelState);
        return Ok(dto with { Id = Guid.NewGuid() });
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 075: Identity / repository

```csharp
using System.Data;
using Dapper;

namespace NovaClient.Data;

public sealed class RoleRepository
{
    private readonly IDbConnection _db;

    public RoleRepository(IDbConnection db) => _db = db;

    public async Task<Role?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from Roles where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<Role>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(Role entity, CancellationToken ct)
    {
        const string sql = @"merge Roles as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}
```

### Item 076: Parsing / dto_mapping

```csharp
namespace SigmaWorker.Mapping;

public static class Mapper
{
    public static Lexer ToDomain(ParserDto dto)
        => new Lexer();

    public static ParserDto ToDto(Lexer entity)
        => new ParserDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
```

### Item 077: Parsing / record_and_validation

- Anchor phrase: **wpf inotifypropertychanged command binding dispatcher**

```csharp
namespace DeltaJobs.Contracts;

public sealed record TokenizerInput(
    Guid TenantId,
    string CorrelationId,
    string RawText,
    int Limit
)
// tag: wpf inotifypropertychanged command binding dispatcher
{
    public TokenizerInput Validate()
    {
        if (TenantId == Guid.Empty) throw new ArgumentException("TenantId must be set");
        if (string.IsNullOrWhiteSpace(CorrelationId)) throw new ArgumentException("CorrelationId required");
        if (Limit is < 1 or > 500) throw new ArgumentOutOfRangeException(nameof(Limit));
        return this;
    }
}
```

### Item 078: Concurrency / controller

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
using Microsoft.AspNetCore.Mvc;

// tag: dapper merge upsert commanddefinition cancellationtoken
namespace GammaWorker.Api;

[ApiController]
[Route("api/concurrency")]
public sealed class SemaphoreSlimController : ControllerBase
{
    [HttpPost("create")]
    public ActionResult<ChannelDto> Create([FromBody] ChannelDto dto)
    {
        if (!ModelState.IsValid) return BadRequest(ModelState);
        return Ok(dto with { Id = Guid.NewGuid() });
    }
}

#if DEBUG
// debug-only path
#endif
```

### Item 079: Identity / extension_method

- Anchor phrase: **yaml pipeline step id next loop guard context budget**

```csharp
namespace BetaServer.Extensions;

public static class PermissionExtensions
{
    public static bool IsEmpty(this Permission? value)
// NOTE: yaml pipeline step id next loop guard context budget
        => value is null || value.Equals(default(Permission));
}
```

### Item 080: Networking / linq_transform

- Anchor phrase: **acl filter applied before ranking**

```csharp
namespace ZenithWorker.Linq;

public static class HttpClientQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
// keyword: acl filter applied before ranking
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 081: Concurrency / repository

- Anchor phrase: **weaviate byov vector import snapshot head_sha**

```csharp
using System.Data;
using Dapper;

#region FileHeader
// Generated sample
// tag: weaviate byov vector import snapshot head_sha
#endregion

namespace GammaUtils.Data;

public sealed class SemaphoreSlimRepository
{
    private readonly IDbConnection _db;

    public SemaphoreSlimRepository(IDbConnection db) => _db = db;

    public async Task<SemaphoreSlim?> GetByIdAsync(Guid id, CancellationToken ct)
    {
        const string sql = @"select top(1) * from SemaphoreSlims where Id = @id";
        return await _db.QuerySingleOrDefaultAsync<SemaphoreSlim>(new CommandDefinition(sql, new { id }, cancellationToken: ct));
    }

    public async Task<int> UpsertAsync(SemaphoreSlim entity, CancellationToken ct)
    {
        const string sql = @"merge SemaphoreSlims as t
using (select @Id as Id) as s
on t.Id = s.Id
when matched then update set UpdatedAtUtc = sysutcdatetime()
when not matched then insert (Id, CreatedAtUtc) values (@Id, sysutcdatetime());";
        return await _db.ExecuteAsync(new CommandDefinition(sql, new { entity.Id }, cancellationToken: ct));
    }
}
public sealed record SnapshotRef(string head_sha, string branch_name);
```

### Item 082: Data / dto_mapping

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace GammaApi.Mapping;

public static class Mapper
{
    public static DbContext ToDomain(DbContextDto dto)
// tag: nlog archiveNumbering Date archiveDateFormat
        => new DbContext();

    public static DbContextDto ToDto(DbContext entity)
        => new DbContextDto(Id: Guid.NewGuid(), Name: entity.ToString() ?? "");
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 083: Search / linq_transform

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace OmegaCore.Linq;

public static class RankQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
// tag: rsa decrypt base64 pem private key
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 084: Search / linq_transform

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
namespace ZenithUtils.Linq;

public static class EmbeddingQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
// keyword: rsa decrypt base64 pem private key
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}

#if DEBUG
// debug-only path
#endif
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 085: Parsing / extension_method

```csharp
namespace AlphaJobs.Extensions;

public static class NormalizeExtensions
{
    public static bool IsEmpty(this Normalize? value)
        => value is null || value.Equals(default(Normalize));
}
```

### Item 086: Parsing / async_pipeline

```csharp
using System.Threading.Channels;

namespace AtlasSdk.Pipeline;

#nullable enable

public sealed class LexerStep
{
    public async Task RunAsync(ChannelReader<string> input, ChannelWriter<string> output, CancellationToken ct)
    {
        await foreach (var item in input.ReadAllAsync(ct))
        {
            if (string.IsNullOrWhiteSpace(item)) continue;
            var normalized = item.Trim().ToLowerInvariant();
            await output.WriteAsync(normalized, ct);
        }
        output.Complete();
    }
}
```

### Item 087: Networking / controller

- Anchor phrase: **rsa decrypt base64 pem private key**

```csharp
using Microsoft.AspNetCore.Mvc;

namespace NimbusCore.Api;

[ApiController]
[Route("api/networking")]
public sealed class CircuitBreakerController : ControllerBase
// tag: rsa decrypt base64 pem private key
{
    [HttpPost("create")]
    public ActionResult<HttpClientDto> Create([FromBody] HttpClientDto dto)
    {
        if (!ModelState.IsValid) return BadRequest(ModelState);
        return Ok(dto with { Id = Guid.NewGuid() });
    }
}
public static byte[] FromBase64(string s) => Convert.FromBase64String(s);
```

### Item 088: Data / controller

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
using Microsoft.AspNetCore.Mvc;

namespace NovaWorker.Api;

[ApiController]
[Route("api/data")]
// tag: dapper merge upsert commanddefinition cancellationtoken
public sealed class DbContextController : ControllerBase
{
    [HttpPost("create")]
    public ActionResult<DbContextDto> Create([FromBody] DbContextDto dto)
    {
        if (!ModelState.IsValid) return BadRequest(ModelState);
        return Ok(dto with { Id = Guid.NewGuid() });
    }
}
```

### Item 089: Parsing / unit_test

```csharp
using Xunit;

namespace SigmaApi.Tests;

#nullable enable

public sealed class LexerServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 090: Parsing / exceptions_and_result

```csharp
namespace BetaClient.Common;

public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

#nullable enable

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("DUPLICATE");
    }
}
```

### Item 091: UI / extension_method

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace NimbusSdk.Extensions;

public static class ValidationExtensions
// tag: nlog archiveNumbering Date archiveDateFormat
{
    public static bool IsEmpty(this Validation? value)
        => value is null || value.Equals(default(Validation));
}

#if DEBUG
// debug-only path
#endif
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 092: Parsing / linq_transform

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
#region FileHeader
// Generated sample
#endregion

namespace OrionUtils.Linq;

public static class RegexQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
// keyword: nlog archiveNumbering Date archiveDateFormat
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}

#if DEBUG
// debug-only path
#endif
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 093: Data / linq_transform

```csharp
namespace KappaWorker.Linq;

public static class EfCoreQueries
{
    public static IReadOnlyList<string> TopTokens(IEnumerable<string> tokens)
        => tokens
            .Where(t => t.Length >= 3)
            .Select(t => t.ToLowerInvariant())
            .GroupBy(t => t)
            .OrderByDescending(g => g.Count())
            .ThenBy(g => g.Key)
            .Take(10)
            .Select(g => g.Key)
            .ToList();
}
```

### Item 094: UI / extension_method

```csharp
namespace AlphaSdk.Extensions;

public static class CommandExtensions
{
    public static bool IsEmpty(this Command? value)
        => value is null || value.Equals(default(Command));
}
```

### Item 095: Cache / exceptions_and_result

- Anchor phrase: **nlog archiveNumbering Date archiveDateFormat**

```csharp
namespace AlphaClient.Common;

// keyword: nlog archiveNumbering Date archiveDateFormat
public readonly record struct Result(bool Ok, string? Error)
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("DUPLICATE");
    }
}
/* nlog.config: archiveNumbering="Date" archiveDateFormat="yyyy-MM-dd" */
```

### Item 096: Concurrency / unit_test

```csharp
using Xunit;

namespace GammaJobs.Tests;

#nullable enable

public sealed class ChannelServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 097: Logging / unit_test

- Anchor phrase: **weaviate byov vector import snapshot head_sha**

```csharp
using Xunit;

namespace NovaJobs.Tests;
// tag: weaviate byov vector import snapshot head_sha

#nullable enable

public sealed class AuditLogServiceTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
public sealed record SnapshotRef(string head_sha, string branch_name);
```

### Item 098: Parsing / service_class

- Anchor phrase: **acl filter applied before ranking**

```csharp
#region FileHeader
// Generated sample
#endregion
// NOTE: acl filter applied before ranking

namespace NovaDomain.Services;

public sealed class ParserProcessor
{
    private readonly ILogger<ParserProcessor> _log;
    private readonly IClock _clock;

    public ParserProcessor(ILogger<ParserProcessor> log, IClock clock)
    {
        _log = log;
        _clock = clock;
    }

    public async ValueTask<Result> CreateAsync(Canonicalize input, CancellationToken ct)
    {
        using var scope = _log.BeginScope("corr={CorrelationId}", input.CorrelationId);
        _log.LogInformation("Start Parsing Canonicalize at {UtcNow}", _clock.UtcNow);

        if (input is null) return Result.Fail("INPUT_NULL");

        await Task.Delay(10, ct); // simulate work
        return Result.Ok();
    }
}
public sealed record AclMeta(Guid TenantId, int[] allowed_group_ids);
```

### Item 099: Crypto / unit_test

```csharp
using Xunit;

namespace AtlasApi.Tests;

public sealed class KeyVaultHandlerTests
{
    [Fact]
    public void Throws_when_tenant_is_empty()
    {
        var ex = Assert.Throws<ArgumentException>(() => new Guid("00000000-0000-0000-0000-000000000000"));
        Assert.NotNull(ex);
    }
}
```

### Item 100: Networking / exceptions_and_result

- Anchor phrase: **dapper merge upsert commanddefinition cancellationtoken**

```csharp
namespace SigmaCore.Common;

public readonly record struct Result(bool Ok, string? Error)
// keyword: dapper merge upsert commanddefinition cancellationtoken
{
    public static Result Success() => new(true, null);
    public static Result Fail(string error) => new(false, error);
}

#nullable enable

public sealed class DomainException : Exception
{
    public DomainException(string code) : base(code) { }
}

public static class Guard
{
    public static void Ensure(bool condition, string errorCode)
    {
        if (!condition) throw new DomainException("DUPLICATE");
    }
}
```
