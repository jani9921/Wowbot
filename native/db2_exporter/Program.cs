using DBCD;
using DBCD.Providers;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using System.Security.Cryptography;

// Static client-file conversion only: no process, game API, input, hotfix
// mutation, authentication/session material or online data provider.
if (args.Length < 4)
{
    Console.Error.WriteLine("Usage: Db2Export <db2-directory> <dbd-directory> <new-output-directory> <table>...");
    return 2;
}
var source = Path.GetFullPath(args[0]);
var definitions = Path.GetFullPath(args[1]);
var output = Path.GetFullPath(args[2]);
Directory.CreateDirectory(output);
var reader = new DBCD.DBCD(new FilesystemDBCProvider(source), new FilesystemDBDProvider(definitions));
var options = new JsonSerializerOptions { NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals };
var failed = false;
foreach (var name in args.Skip(3))
{
    if (!Regex.IsMatch(name, @"\A[A-Za-z][A-Za-z0-9_]*\z"))
        throw new ArgumentException("Invalid DB2 table name");
    try
    {
        using var sourceFile = File.OpenRead(Path.Combine(source, name + ".db2"));
        var sourceHash = Convert.ToHexString(SHA256.HashData(sourceFile)).ToLowerInvariant();
        using var definitionFile = File.OpenRead(Path.Combine(definitions, name + ".dbd"));
        var definitionHash = Convert.ToHexString(SHA256.HashData(definitionFile)).ToLowerInvariant();
        // WDC layouts are matched to the pinned DBD definitions. The static
        // schema label is not asserted to be the live installation build.
        var storage = reader.Load(name);
        var destination = Path.Combine(output, name + ".jsonl");
        using var file = new StreamWriter(new FileStream(destination, FileMode.CreateNew, FileAccess.Write));
        file.WriteLine(JsonSerializer.Serialize(new {
            type = "table", name, row_count = storage.Count, layout_hash = storage.LayoutHash.ToString("X8"),
            source_sha256 = sourceHash, definition_sha256 = definitionHash,
            columns = storage.AvailableColumns
        }, options));
        foreach (var pair in storage.ToDictionary())
        {
            var values = new Dictionary<string, object?>();
            foreach (var column in storage.AvailableColumns)
                values[column] = pair.Value[column];
            file.WriteLine(JsonSerializer.Serialize(new { type = "row", table = name, id = pair.Key, values }, options));
        }
        Console.WriteLine(JsonSerializer.Serialize(new { table = name, status = "decoded", rows = storage.Count }));
    }
    catch (Exception error)
    {
        failed = true;
        Console.WriteLine(JsonSerializer.Serialize(new { table = name, status = "failed", error = error.GetType().Name, message = error.Message, stack = error.StackTrace }));
    }
}
return failed ? 1 : 0;
