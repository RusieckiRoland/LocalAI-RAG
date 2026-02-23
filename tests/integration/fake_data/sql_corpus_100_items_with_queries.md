# SQL Code Corpus (100 items) + Retrieval Query Set

This document contains **100** short SQL/T-SQL items with varied structure and vocabulary.

Purpose: test/query design for **BM25**, **semantic**, and **hybrid** retrieval.


---

## Query Sets

### BM25 queries (5)

1. `OPENJSON with schema TenantId CorrelationId "openjson(@payload) with" sql server`
2. `apply filter before ranking tenant_id allowed_group_ids_json exists openjson UserGroups ACL`
3. `merge upsert pattern "when matched then update" sysutcdatetime sql server`
4. `order by offset fetch next pagination @offset @limit stored procedure`
5. `head_sha snapshot branch import RagEdge EdgeType Calls ReadsFrom WritesTo`

### Semantic queries (5)

1. Find SQL code that enforces ACL by prefiltering rows using tenant and group membership, explicitly applying filters before any ranking or limiting.
2. Show examples of SQL Server JSON parsing with OPENJSON and an explicit WITH schema that extracts tenantId and correlationId fields.
3. Locate T-SQL MERGE-based upsert statements that update timestamps with sysutcdatetime() and insert when not matched.
4. Find stored procedures that implement pagination using ORDER BY ... OFFSET ... FETCH NEXT ... and accept @offset/@limit parameters.
5. Find schema or DDL for a dependency/graph edge table that includes snapshot identifiers like head_sha and an EdgeType such as Calls/ReadsFrom/WritesTo.

### Hybrid queries (5)

1. `("apply filter before ranking" OR prefilter) AND (tenant_id OR TenantId) AND (allowed_group_ids OR UserGroups)`
2. `(OPENJSON OR json) AND ("with (" OR "with(") AND (TenantId OR CorrelationId)`
3. `(MERGE OR upsert) AND ("when matched" OR "when not matched") AND sysutcdatetime`
4. `(OFFSET AND FETCH) AND (pagination OR @offset OR @limit) AND (order by)`
5. `(head_sha OR snapshot) AND (RagEdge OR EdgeType OR dependencies) AND (Calls OR ReadsFrom OR WritesTo)`

---

## Corpus Items (100)

### Item 001: Billing / function_table_valued

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
-- region: generated sample
set ansi_nulls on;
set quoted_identifier on;
-- keyword: lease 15 minutes with heartbeat

create or alter function [app].[tvf_Invoice_Search](
    @tenant_id uniqueidentifier,
    @q nvarchar(200)
)
returns table
as
return
(
    select top (50) *
    from [app].[Ledger_Events]
    where TenantId = @tenant_id
      and (Name like '%' + @q + '%' or Code like '%' + @q + '%')
    order by UpdatedAtUtc desc
);
```

### Item 002: Data / stored_procedure_crud

- Anchor phrase: **apply filter before ranking**

```sql
-- region: generated sample
create or alter procedure [sec].[sp_Order_Upsert]
    @id uniqueidentifier,
-- keyword: apply filter before ranking
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: deduplicate by checksum sha256

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [sec].[Order_Events] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 003: Analytics / transaction_with_try_catch

```sql
-- region: generated sample
begin try
    begin tran;

    insert into [app].[Fact_Events](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch

GO
```

### Item 004: Identity / stored_procedure_crud

- Anchor phrase: **order by offset fetch**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: order by offset fetch
create or alter procedure [report].[sp_User_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: lease 15 minutes with heartbeat

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [report].[Role_Log] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 005: Logging / temp_table_pipeline

- Anchor phrase: **openjson with schema**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: openjson with schema
create table #tmp_tokens(
    token nvarchar(200) not null,
    cnt int not null
);

insert into #tmp_tokens(token, cnt)
select value, count(*)
from string_split(@text, ' ')
where len(value) >= 3
group by value;

select top (10) token, cnt
from #tmp_tokens
order by cnt desc, token asc;

drop table #tmp_tokens;
```

### Item 006: Analytics / index_and_constraint

```sql
set ansi_nulls on;
set quoted_identifier on;

-- index + constraint
alter table [audit].[Dim_Log]
add constraint CK_Fact_Tenant_NotNull check (TenantId is not null);

create index IX_Fact_Tenant_CreatedAt
on [audit].[Dim_Log](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 007: Security / acl_prefilter_query

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
-- region: generated sample
-- ACL prefilter: apply filter before ranking
select top (100) *
-- keyword: lease 15 minutes with heartbeat
from [report].[Certificate_Events]
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [report].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 008: Billing / function_scalar

```sql
create or alter function [app].[fn_Invoice_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end
```

### Item 009: Jobs / json_parse

- Anchor phrase: **snapshot head_sha branch import**

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

-- keyword: snapshot head_sha branch import
select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema
```

### Item 010: Identity / json_parse

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: lease 15 minutes with heartbeat
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema

GO
```

### Item 011: Search / transaction_with_try_catch

- Anchor phrase: **reciprocal rank fusion rrf tie-break**

```sql
begin try
    begin tran;

-- keyword: reciprocal rank fusion rrf tie-break
    insert into [audit].[Bm25s](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 012: Files / transaction_with_try_catch

```sql
begin try
    begin tran;

    insert into [app].[Checksums](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 013: Data / transaction_with_try_catch

- Anchor phrase: **snapshot head_sha branch import**

```sql
begin try
    begin tran;

-- keyword: snapshot head_sha branch import
    insert into [sync].[Order_Queue](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch

GO
```

### Item 014: Data / acl_prefilter_query

- Anchor phrase: **rsa decrypt base64 private key**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [etl].[Products]
-- keyword: rsa decrypt base64 private key
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [etl].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 015: Identity / acl_prefilter_query

- Anchor phrase: **deduplicate by checksum sha256**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: deduplicate by checksum sha256
-- ACL prefilter: apply filter before ranking
select top (100) *
from [report].[Role_Events]
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [report].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 016: Jobs / stored_procedure_crud

```sql
create or alter procedure [sec].[sp_Lease_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: apply filter before ranking

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [sec].[Worker_Queue] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 017: Security / function_table_valued

- Anchor phrase: **openjson with schema**

```sql
create or alter function [audit].[tvf_Certificate_Search](
    @tenant_id uniqueidentifier,
    @q nvarchar(200)
-- keyword: openjson with schema
)
returns table
as
return
(
    select top (50) *
    from [audit].[Certificate_Items]
    where TenantId = @tenant_id
      and (Name like '%' + @q + '%' or Code like '%' + @q + '%')
    order by UpdatedAtUtc desc
);
```

### Item 018: Shipping / json_parse

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

-- keyword: lease 15 minutes with heartbeat
select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema
```

### Item 019: Search / transaction_with_try_catch

- Anchor phrase: **rsa decrypt base64 private key**

```sql
begin try
    begin tran;

-- keyword: rsa decrypt base64 private key
    insert into [dbo].[Bm25_Items](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 020: Analytics / function_scalar

- Anchor phrase: **openjson with schema**

```sql
create or alter function [app].[fn_Fact_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
-- keyword: openjson with schema
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end

GO
```

### Item 021: Identity / index_and_constraint

- Anchor phrase: **order by offset fetch**

```sql
-- index + constraint
alter table [ops].[Permission_Map]
add constraint CK_User_Tenant_NotNull check (TenantId is not null);
-- keyword: order by offset fetch

create index IX_User_Tenant_CreatedAt
on [ops].[Permission_Map](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 022: Data / transaction_with_try_catch

- Anchor phrase: **order by offset fetch**

```sql
begin try
    begin tran;

-- keyword: order by offset fetch
    insert into [etl].[Order_Log](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 023: Data / graph_expansion_edges

```sql
-- Graph expansion edges table (dependencies)
create table [app].[RagEdge](
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 024: Jobs / merge_upsert

- Anchor phrase: **reciprocal rank fusion rrf tie-break**

```sql
-- MERGE upsert pattern
merge [sync].[Lease_Map] as t
using (select @Id as Id, @TenantId as TenantId) as s
-- keyword: reciprocal rank fusion rrf tie-break
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 025: Jobs / transaction_with_try_catch

```sql
begin try
    begin tran;

    insert into [report].[Lease_Log](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch

GO
```

### Item 026: Files / temp_table_pipeline

- Anchor phrase: **order by offset fetch**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: order by offset fetch
create table #tmp_tokens(
    token nvarchar(200) not null,
    cnt int not null
);

insert into #tmp_tokens(token, cnt)
select value, count(*)
from string_split(@text, ' ')
where len(value) >= 3
group by value;

select top (10) token, cnt
from #tmp_tokens
order by cnt desc, token asc;

drop table #tmp_tokens;
```

### Item 027: Analytics / graph_expansion_edges

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: lease 15 minutes with heartbeat
-- Graph expansion edges table (dependencies)
create table [sync].[RagEdge](
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 028: Logging / graph_expansion_edges

```sql
-- Graph expansion edges table (dependencies)
create table [ops].[RagEdge](
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 029: Identity / stored_procedure_report

- Anchor phrase: **openjson with schema**

```sql
create or alter procedure [dbo].[sp_User_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
-- keyword: openjson with schema
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [dbo].[Acl_Queue]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end

GO
```

### Item 030: Identity / merge_upsert

```sql
-- MERGE upsert pattern
merge [sync].[User_Log] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 031: Search / graph_expansion_edges

- Anchor phrase: **rsa decrypt base64 private key**

```sql
-- Graph expansion edges table (dependencies)
create table [dbo].[RagEdge](
    EdgeId uniqueidentifier not null,
-- keyword: rsa decrypt base64 private key
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 032: Search / view_with_cte

- Anchor phrase: **rsa decrypt base64 private key**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: rsa decrypt base64 private key
create or alter view [audit].[vw_Bm25_Latest]
as
with ranked as (
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [audit].[Hybrid_Map]
)
select *
from ranked
where rn = 1;

GO
```

### Item 033: Files / view_with_cte

- Anchor phrase: **order by offset fetch**

```sql
create or alter view [etl].[vw_Blob_Latest]
as
with ranked as (
-- keyword: order by offset fetch
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [etl].[Checksum_Map]
)
select *
from ranked
where rn = 1;
```

### Item 034: Analytics / json_parse

- Anchor phrase: **order by offset fetch**

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

-- keyword: order by offset fetch
select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema

GO
```

### Item 035: Shipping / stored_procedure_crud

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
create or alter procedure [audit].[sp_Shipment_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
-- keyword: archiveNumbering Date archiveDateFormat
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: deduplicate by checksum sha256

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [audit].[TrackingNumber_Map] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 036: Billing / function_scalar

```sql
-- region: generated sample
set ansi_nulls on;
set quoted_identifier on;

create or alter function [etl].[fn_Invoice_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end
```

### Item 037: Files / stored_procedure_crud

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
create or alter procedure [dbo].[sp_Blob_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
-- keyword: lease 15 minutes with heartbeat
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: lease 15 minutes with heartbeat

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [dbo].[Blob_Queue] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 038: Logging / json_parse

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema
```

### Item 039: Jobs / json_parse

- Anchor phrase: **apply filter before ranking**

```sql
-- region: generated sample
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;
-- keyword: apply filter before ranking

select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema
```

### Item 040: Identity / stored_procedure_report

- Anchor phrase: **deduplicate by checksum sha256**

```sql
create or alter procedure [ops].[sp_User_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
-- keyword: deduplicate by checksum sha256
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [ops].[Permission_Log]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 041: Billing / stored_procedure_report

- Anchor phrase: **snapshot head_sha branch import**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: snapshot head_sha branch import
create or alter procedure [app].[sp_Invoice_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [app].[VatRate_Queue]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 042: Security / view_with_cte

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
create or alter view [dbo].[vw_Certificate_Latest]
as
with ranked as (
-- keyword: archiveNumbering Date archiveDateFormat
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [dbo].[Certificates]
)
select *
from ranked
where rn = 1;

GO
```

### Item 043: Jobs / stored_procedure_crud

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
-- region: generated sample
create or alter procedure [dbo].[sp_Lease_Upsert]
    @id uniqueidentifier,
-- keyword: archiveNumbering Date archiveDateFormat
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: lease 15 minutes with heartbeat

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [dbo].[Leases] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end

GO
```

### Item 044: Logging / function_scalar

- Anchor phrase: **deduplicate by checksum sha256**

```sql
create or alter function [audit].[fn_AuditLog_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
-- keyword: deduplicate by checksum sha256
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end

GO
```

### Item 045: Data / function_scalar

- Anchor phrase: **snapshot head_sha branch import**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: snapshot head_sha branch import
create or alter function [dbo].[fn_Order_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end

GO
```

### Item 046: Files / stored_procedure_crud

- Anchor phrase: **rsa decrypt base64 private key**

```sql
create or alter procedure [report].[sp_Blob_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
-- keyword: rsa decrypt base64 private key
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: lease 15 minutes with heartbeat

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [report].[Checksum_Log] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end

GO
```

### Item 047: Data / merge_upsert

```sql
-- region: generated sample
-- MERGE upsert pattern
merge [dbo].[Customer_Log] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 048: Analytics / merge_upsert

- Anchor phrase: **apply filter before ranking**

```sql
-- MERGE upsert pattern
merge [ops].[Fact_Queue] as t
using (select @Id as Id, @TenantId as TenantId) as s
-- keyword: apply filter before ranking
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 049: Logging / function_scalar

- Anchor phrase: **openjson with schema**

```sql
create or alter function [sync].[fn_AuditLog_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
-- keyword: openjson with schema
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end
```

### Item 050: Identity / transaction_with_try_catch

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: archiveNumbering Date archiveDateFormat
begin try
    begin tran;

    insert into [dbo].[Role_Queue](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 051: Data / view_with_cte

- Anchor phrase: **reciprocal rank fusion rrf tie-break**

```sql
create or alter view [app].[vw_Order_Latest]
as
with ranked as (
-- keyword: reciprocal rank fusion rrf tie-break
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [app].[Order_Queue]
)
select *
from ranked
where rn = 1;
```

### Item 052: Search / merge_upsert

```sql
set ansi_nulls on;
set quoted_identifier on;

-- MERGE upsert pattern
merge [sec].[Hybrid_Map] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 053: Files / stored_procedure_report

```sql
create or alter procedure [sync].[sp_Blob_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [sync].[Sha256_Queue]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 054: Billing / stored_procedure_report

- Anchor phrase: **snapshot head_sha branch import**

```sql
create or alter procedure [app].[sp_Invoice_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
-- keyword: snapshot head_sha branch import
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [app].[Invoice_Map]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 055: Identity / transaction_with_try_catch

```sql
set ansi_nulls on;
set quoted_identifier on;

begin try
    begin tran;

    insert into [dbo].[Role_Items](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch

GO
```

### Item 056: Shipping / view_with_cte

```sql
create or alter view [report].[vw_Shipment_Latest]
as
with ranked as (
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [report].[Label_Items]
)
select *
from ranked
where rn = 1;
```

### Item 057: Shipping / temp_table_pipeline

```sql
set ansi_nulls on;
set quoted_identifier on;

create table #tmp_tokens(
    token nvarchar(200) not null,
    cnt int not null
);

insert into #tmp_tokens(token, cnt)
select value, count(*)
from string_split(@text, ' ')
where len(value) >= 3
group by value;

select top (10) token, cnt
from #tmp_tokens
order by cnt desc, token asc;

drop table #tmp_tokens;

GO
```

### Item 058: Search / function_table_valued

- Anchor phrase: **order by offset fetch**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: order by offset fetch
create or alter function [sync].[tvf_Bm25_Search](
    @tenant_id uniqueidentifier,
    @q nvarchar(200)
)
returns table
as
return
(
    select top (50) *
    from [sync].[Bm25_Queue]
    where TenantId = @tenant_id
      and (Name like '%' + @q + '%' or Code like '%' + @q + '%')
    order by UpdatedAtUtc desc
);
```

### Item 059: Billing / transaction_with_try_catch

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
begin try
    begin tran;

-- keyword: archiveNumbering Date archiveDateFormat
    insert into [app].[Invoice_Items](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 060: Jobs / temp_table_pipeline

```sql
-- region: generated sample
create table #tmp_tokens(
    token nvarchar(200) not null,
    cnt int not null
);

insert into #tmp_tokens(token, cnt)
select value, count(*)
from string_split(@text, ' ')
where len(value) >= 3
group by value;

select top (10) token, cnt
from #tmp_tokens
order by cnt desc, token asc;

drop table #tmp_tokens;
```

### Item 061: Logging / stored_procedure_report

- Anchor phrase: **openjson with schema**

```sql
create or alter procedure [ops].[sp_AuditLog_Report]
    @tenant_id uniqueidentifier,
    @date_from datetime2,
-- keyword: openjson with schema
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [ops].[AuditLog_Log]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 062: Shipping / graph_expansion_edges

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
-- Graph expansion edges table (dependencies)
create table [dbo].[RagEdge](
    EdgeId uniqueidentifier not null,
-- keyword: lease 15 minutes with heartbeat
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 063: Identity / acl_prefilter_query

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [audit].[Role_Queue]
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [audit].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;

GO
```

### Item 064: Identity / graph_expansion_edges

- Anchor phrase: **snapshot head_sha branch import**

```sql
-- Graph expansion edges table (dependencies)
create table [report].[RagEdge](
    EdgeId uniqueidentifier not null,
-- keyword: snapshot head_sha branch import
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 065: Files / json_parse

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema

GO
```

### Item 066: Analytics / stored_procedure_report

- Anchor phrase: **order by offset fetch**

```sql
-- region: generated sample
create or alter procedure [ops].[sp_Fact_Report]
    @tenant_id uniqueidentifier,
-- keyword: order by offset fetch
    @date_from datetime2,
    @date_to datetime2,
    @offset int = 0,
    @limit int = 100
as
begin
    set nocount on;

    ;with base as (
        select *
        from [ops].[Dim_Queue]
        where TenantId = @tenant_id
          and CreatedAtUtc >= @date_from
          and CreatedAtUtc <  @date_to
    )
    select *
    from base
    order by CreatedAtUtc desc
    offset @offset rows fetch next @limit rows only; -- order by offset fetch (pagination)
end
```

### Item 067: Data / acl_prefilter_query

- Anchor phrase: **reciprocal rank fusion rrf tie-break**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [report].[Product_Log]
-- keyword: reciprocal rank fusion rrf tie-break
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [report].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 068: Data / stored_procedure_crud

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
create or alter procedure [app].[sp_Order_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
-- keyword: archiveNumbering Date archiveDateFormat
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: lease 15 minutes with heartbeat

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [app].[Customer_Events] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 069: Analytics / transaction_with_try_catch

```sql
begin try
    begin tran;

    insert into [sec].[Fact_Map](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 070: Security / merge_upsert

- Anchor phrase: **rsa decrypt base64 private key**

```sql
-- MERGE upsert pattern
merge [sync].[PrivateKey_Queue] as t
using (select @Id as Id, @TenantId as TenantId) as s
-- keyword: rsa decrypt base64 private key
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 071: Data / acl_prefilter_query

- Anchor phrase: **snapshot head_sha branch import**

```sql
-- region: generated sample
set ansi_nulls on;
set quoted_identifier on;
-- keyword: snapshot head_sha branch import

-- ACL prefilter: apply filter before ranking
select top (100) *
from [ops].[Order_Items]
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [ops].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 072: Data / stored_procedure_crud

```sql
create or alter procedure [sec].[sp_Order_Upsert]
    @id uniqueidentifier,
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: apply filter before ranking

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [sec].[Order_Queue] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 073: Logging / json_parse

```sql
-- JSON parse example (OPENJSON with schema)
declare @payload nvarchar(max) = @json;

select j.*
from openjson(@payload)
with (
    Id uniqueidentifier '$.id',
    TenantId uniqueidentifier '$.tenantId',
    CorrelationId nvarchar(64) '$.correlationId',
    Value nvarchar(200) '$.value'
) as j;

-- keyword: openjson with schema
```

### Item 074: Files / acl_prefilter_query

- Anchor phrase: **deduplicate by checksum sha256**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [ops].[Blobs]
-- keyword: deduplicate by checksum sha256
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [ops].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 075: Jobs / graph_expansion_edges

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
-- region: generated sample
-- Graph expansion edges table (dependencies)
create table [app].[RagEdge](
-- keyword: lease 15 minutes with heartbeat
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 076: Data / merge_upsert

```sql
-- MERGE upsert pattern
merge [etl].[Product_Log] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 077: Analytics / graph_expansion_edges

- Anchor phrase: **order by offset fetch**

```sql
-- region: generated sample
-- Graph expansion edges table (dependencies)
create table [sync].[RagEdge](
-- keyword: order by offset fetch
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import

GO
```

### Item 078: Jobs / acl_prefilter_query

- Anchor phrase: **apply filter before ranking**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [dbo].[Worker_Queue]
-- keyword: apply filter before ranking
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [dbo].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 079: Data / function_scalar

- Anchor phrase: **openjson with schema**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: openjson with schema
create or alter function [dbo].[fn_Order_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end

GO
```

### Item 080: Jobs / transaction_with_try_catch

```sql
set ansi_nulls on;
set quoted_identifier on;

begin try
    begin tran;

    insert into [ops].[Lease_Items](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch
```

### Item 081: Shipping / transaction_with_try_catch

```sql
begin try
    begin tran;

    insert into [app].[Label_Log](Id, TenantId, CreatedAtUtc)
    values (newid(), @tenant_id, sysutcdatetime());

    -- keyword: rsa decrypt base64 private key
    commit;
end try
begin catch
    if @@trancount > 0 rollback;
    declare @msg nvarchar(4000) = error_message();
    throw 50001, @msg, 1;
end catch

GO
```

### Item 082: Data / view_with_cte

```sql
create or alter view [etl].[vw_Order_Latest]
as
with ranked as (
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [etl].[Orders]
)
select *
from ranked
where rn = 1;
```

### Item 083: Jobs / index_and_constraint

- Anchor phrase: **lease 15 minutes with heartbeat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: lease 15 minutes with heartbeat
-- index + constraint
alter table [dbo].[Workers]
add constraint CK_Lease_Tenant_NotNull check (TenantId is not null);

create index IX_Lease_Tenant_CreatedAt
on [dbo].[Workers](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 084: Data / merge_upsert

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: archiveNumbering Date archiveDateFormat
-- MERGE upsert pattern
merge [app].[Customer_Log] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());

GO
```

### Item 085: Search / merge_upsert

```sql
-- MERGE upsert pattern
merge [report].[Bm25_Events] as t
using (select @Id as Id, @TenantId as TenantId) as s
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 086: Analytics / index_and_constraint

- Anchor phrase: **snapshot head_sha branch import**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: snapshot head_sha branch import
-- index + constraint
alter table [sec].[Fact_Events]
add constraint CK_Fact_Tenant_NotNull check (TenantId is not null);

create index IX_Fact_Tenant_CreatedAt
on [sec].[Fact_Events](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 087: Logging / index_and_constraint

- Anchor phrase: **rsa decrypt base64 private key**

```sql
-- index + constraint
alter table [ops].[CorrelationId_Map]
add constraint CK_AuditLog_Tenant_NotNull check (TenantId is not null);
-- keyword: rsa decrypt base64 private key

create index IX_AuditLog_Tenant_CreatedAt
on [ops].[CorrelationId_Map](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 088: Shipping / acl_prefilter_query

- Anchor phrase: **openjson with schema**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [audit].[Labels]
-- keyword: openjson with schema
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [audit].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;
```

### Item 089: Identity / function_scalar

```sql
set ansi_nulls on;
set quoted_identifier on;

create or alter function [dbo].[fn_User_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end
```

### Item 090: Search / temp_table_pipeline

```sql
create table #tmp_tokens(
    token nvarchar(200) not null,
    cnt int not null
);

insert into #tmp_tokens(token, cnt)
select value, count(*)
from string_split(@text, ' ')
where len(value) >= 3
group by value;

select top (10) token, cnt
from #tmp_tokens
order by cnt desc, token asc;

drop table #tmp_tokens;

GO
```

### Item 091: Jobs / graph_expansion_edges

```sql
-- Graph expansion edges table (dependencies)
create table [app].[RagEdge](
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import
```

### Item 092: Identity / view_with_cte

- Anchor phrase: **snapshot head_sha branch import**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: snapshot head_sha branch import
create or alter view [sync].[vw_User_Latest]
as
with ranked as (
    select
        *,
        row_number() over(partition by TenantId, Id order by UpdatedAtUtc desc) as rn
    from [sync].[Permission_Log]
)
select *
from ranked
where rn = 1;
```

### Item 093: Security / function_table_valued

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
set ansi_nulls on;
set quoted_identifier on;

-- keyword: archiveNumbering Date archiveDateFormat
create or alter function [etl].[tvf_Certificate_Search](
    @tenant_id uniqueidentifier,
    @q nvarchar(200)
)
returns table
as
return
(
    select top (50) *
    from [etl].[PublicKey_Events]
    where TenantId = @tenant_id
      and (Name like '%' + @q + '%' or Code like '%' + @q + '%')
    order by UpdatedAtUtc desc
);
```

### Item 094: Analytics / index_and_constraint

- Anchor phrase: **apply filter before ranking**

```sql
-- index + constraint
alter table [dbo].[Fact_Items]
add constraint CK_Fact_Tenant_NotNull check (TenantId is not null);
-- keyword: apply filter before ranking

create index IX_Fact_Tenant_CreatedAt
on [dbo].[Fact_Items](TenantId, CreatedAtUtc desc)
include (UpdatedAtUtc, CorrelationId);
```

### Item 095: Logging / stored_procedure_crud

- Anchor phrase: **reciprocal rank fusion rrf tie-break**

```sql
-- region: generated sample
create or alter procedure [sync].[sp_AuditLog_Upsert]
    @id uniqueidentifier,
-- keyword: reciprocal rank fusion rrf tie-break
    @tenant_id uniqueidentifier,
    @correlation_id nvarchar(64),
    @payload nvarchar(max)
as
begin
    set nocount on;

    -- keyword: apply filter before ranking

    if (@tenant_id is null) throw 50000, 'TENANT_REQUIRED', 1;

    merge [sync].[AuditLogs] as t
    using (select @id as Id) as s
    on t.Id = s.Id
    when matched then
        update set UpdatedAtUtc = sysutcdatetime(), CorrelationId = @correlation_id, Payload = @payload
    when not matched then
        insert (Id, TenantId, CreatedAtUtc, CorrelationId, Payload)
        values (@id, @tenant_id, sysutcdatetime(), @correlation_id, @payload);

    select @@rowcount as affected_rows;
end
```

### Item 096: Analytics / acl_prefilter_query

- Anchor phrase: **snapshot head_sha branch import**

```sql
-- ACL prefilter: apply filter before ranking
select top (100) *
from [etl].[Kpis]
-- keyword: snapshot head_sha branch import
where TenantId = @tenant_id
  and exists (
      select 1
      from openjson(@allowed_group_ids_json) with (GroupId int '$') g
      where g.GroupId in (select GroupId from [etl].[UserGroups] ug where ug.UserId = @user_id)
  )
order by UpdatedAtUtc desc;

GO
```

### Item 097: Analytics / merge_upsert

- Anchor phrase: **snapshot head_sha branch import**

```sql
-- MERGE upsert pattern
merge [audit].[Fact_Log] as t
using (select @Id as Id, @TenantId as TenantId) as s
-- keyword: snapshot head_sha branch import
on (t.Id = s.Id and t.TenantId = s.TenantId)
when matched then
    update set UpdatedAtUtc = sysutcdatetime()
when not matched then
    insert (Id, TenantId, CreatedAtUtc)
    values (s.Id, s.TenantId, sysutcdatetime());
```

### Item 098: Logging / function_scalar

```sql
create or alter function [report].[fn_AuditLog_Normalize](@input nvarchar(4000))
returns nvarchar(4000)
as
begin
    declare @x nvarchar(4000) = lower(ltrim(rtrim(isnull(@input, ''))));
    -- keyword: deduplicate by checksum sha256
    return @x;
end
```

### Item 099: Analytics / graph_expansion_edges

```sql
set ansi_nulls on;
set quoted_identifier on;

-- Graph expansion edges table (dependencies)
create table [etl].[RagEdge](
    EdgeId uniqueidentifier not null,
    FromNodeId uniqueidentifier not null,
    ToNodeId uniqueidentifier not null,
    EdgeType nvarchar(50) not null, -- Calls / ReadsFrom / WritesTo
    TenantId uniqueidentifier not null,
    head_sha nvarchar(64) not null, -- snapshot head_sha branch import
    CreatedAtUtc datetime2 not null default sysutcdatetime(),
    constraint PK_RagEdge primary key (EdgeId)
);

-- keyword: snapshot head_sha branch import

GO
```

### Item 100: Shipping / function_table_valued

- Anchor phrase: **archiveNumbering Date archiveDateFormat**

```sql
create or alter function [sec].[tvf_Shipment_Search](
    @tenant_id uniqueidentifier,
    @q nvarchar(200)
-- keyword: archiveNumbering Date archiveDateFormat
)
returns table
as
return
(
    select top (50) *
    from [sec].[Shipment_Map]
    where TenantId = @tenant_id
      and (Name like '%' + @q + '%' or Code like '%' + @q + '%')
    order by UpdatedAtUtc desc
);
```
