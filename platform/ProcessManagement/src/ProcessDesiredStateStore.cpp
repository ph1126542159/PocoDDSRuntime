#include "ProcessDesiredStateStore.h"

#include "Poco/DigestEngine.h"
#include "Poco/Exception.h"
#include "Poco/File.h"
#include "Poco/JSON/Array.h"
#include "Poco/JSON/Object.h"
#include "Poco/JSON/Parser.h"
#include "Poco/JSON/Stringifier.h"
#include "Poco/Path.h"
#include "Poco/Process.h"
#include "Poco/SHA2Engine.h"
#include "Poco/Timestamp.h"

#if defined(POCO_OS_FAMILY_WINDOWS)
#include "Poco/UnicodeConverter.h"
#include <Windows.h>
#else
#include <cerrno>
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>
#endif

#include <algorithm>
#include <cctype>
#include <cstdio>
#include <fstream>
#include <limits>
#include <sstream>
#include <utility>
#include <vector>

namespace PocoDDS::ProcessManagement::Detail
{
namespace
{
constexpr std::uint64_t schemaVersion = 1;
constexpr Poco::File::FileSize maximumSnapshotBytes = 1024 * 1024;

std::string temporaryPath(const std::string& path)
{
    return path + ".new";
}

std::string previousPath(const std::string& path)
{
    return path + ".previous";
}

void requireRegularFile(const Poco::File& file, const std::string& role)
{
    if (file.exists() && !file.isFile())
        throw Poco::DataFormatException(
            "Process desired-state " + role + " is not a regular file",
            file.path());
}

std::string canonicalPayload(
    std::uint64_t generation,
    const std::map<std::string, bool>& states)
{
    std::ostringstream payload;
    payload << "schemaVersion=" << schemaVersion << '\n'
            << "generation=" << generation << '\n';
    for (const auto& [name, desiredRunning] : states)
    {
        if (name.empty() || name.size() > 4096 ||
            name.find_first_of("\r\n") != std::string::npos ||
            name.find('\0') != std::string::npos)
            throw Poco::DataFormatException(
                "Process desired-state contains an invalid process name",
                name);
        payload << name.size() << ':' << name << '='
                << (desiredRunning ? '1' : '0') << '\n';
    }
    return payload.str();
}

std::string digest(std::uint64_t generation,
                   const std::map<std::string, bool>& states)
{
    const auto payload = canonicalPayload(generation, states);
    Poco::SHA2Engine engine(Poco::SHA2Engine::SHA_256);
    engine.update(payload);
    return Poco::DigestEngine::digestToHex(engine.digest());
}

std::string readFile(const std::string& path)
{
    Poco::File file(path);
    requireRegularFile(file, "snapshot");
    if (!file.exists())
        throw Poco::FileNotFoundException(
            "Process desired-state snapshot", path);
    if (file.getSize() == 0 || file.getSize() > maximumSnapshotBytes)
        throw Poco::DataFormatException(
            "Process desired-state snapshot size is invalid", path);
    std::ifstream input(path, std::ios::binary);
    if (!input)
        throw Poco::OpenFileException(
            "Cannot open process desired-state snapshot", path);
    return {std::istreambuf_iterator<char>(input),
            std::istreambuf_iterator<char>()};
}

ProcessDesiredStateSnapshot parseSnapshot(const std::string& path)
{
    Poco::JSON::Parser parser;
    const auto root = parser.parse(readFile(path))
                          .extract<Poco::JSON::Object::Ptr>();
    if (!root || root->getValue<Poco::UInt64>("schemaVersion") != schemaVersion)
        throw Poco::DataFormatException(
            "Unsupported process desired-state schema", path);

    ProcessDesiredStateSnapshot result;
    result.available = true;
    result.generation = root->getValue<Poco::UInt64>("generation");
    if (result.generation == 0)
        throw Poco::DataFormatException(
            "Process desired-state generation must be positive", path);

    const auto states = root->getArray("states");
    if (!states || states->size() > 10000)
        throw Poco::DataFormatException(
            "Process desired-state states array is invalid", path);
    for (std::size_t index = 0; index < states->size(); ++index)
    {
        const auto entry = states->getObject(static_cast<unsigned>(index));
        if (!entry)
            throw Poco::DataFormatException(
                "Process desired-state entry is not an object", path);
        const auto name = entry->getValue<std::string>("name");
        const auto desiredRunning = entry->getValue<bool>("desiredRunning");
        canonicalPayload(result.generation, {{name, desiredRunning}});
        if (!result.states.emplace(name, desiredRunning).second)
            throw Poco::DataFormatException(
                "Process desired-state contains a duplicate process", name);
    }

    const auto integrity = root->getObject("integrity");
    if (!integrity ||
        integrity->getValue<std::string>("algorithm") != "SHA-256")
        throw Poco::DataFormatException(
            "Process desired-state integrity algorithm is invalid", path);
    auto expected = integrity->getValue<std::string>("digest");
    std::transform(expected.begin(), expected.end(), expected.begin(),
                   [](unsigned char value) {
                       return static_cast<char>(std::tolower(value));
                   });
    if (expected.size() != 64 ||
        !std::all_of(expected.begin(), expected.end(), [](unsigned char value) {
            return (value >= '0' && value <= '9') ||
                   (value >= 'a' && value <= 'f');
        }) || expected != digest(result.generation, result.states))
        throw Poco::DataFormatException(
            "Process desired-state integrity verification failed", path);
    return result;
}

std::string serialize(std::uint64_t generation,
                      const std::map<std::string, bool>& states)
{
    if (generation == 0)
        throw Poco::InvalidArgumentException(
            "Process desired-state generation must be positive");
    Poco::JSON::Object root;
    root.set("schemaVersion", schemaVersion);
    root.set("generation", generation);
    Poco::JSON::Array::Ptr entries = new Poco::JSON::Array;
    for (const auto& [name, desiredRunning] : states)
    {
        canonicalPayload(generation, {{name, desiredRunning}});
        Poco::JSON::Object::Ptr entry = new Poco::JSON::Object;
        entry->set("name", name);
        entry->set("desiredRunning", desiredRunning);
        entries->add(entry);
    }
    root.set("states", entries);
    Poco::JSON::Object::Ptr integrity = new Poco::JSON::Object;
    integrity->set("algorithm", "SHA-256");
    integrity->set("digest", digest(generation, states));
    root.set("integrity", integrity);
    std::ostringstream output;
    Poco::JSON::Stringifier::stringify(root, output, 2);
    output << '\n';
    return output.str();
}

bool validSnapshot(const std::string& path)
{
    try
    {
        return Poco::File(path).exists() && parseSnapshot(path).available;
    }
    catch (...)
    {
        return false;
    }
}

void writeFileDurably(const std::string& path, const std::string& payload)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring widePath;
    Poco::UnicodeConverter::toUTF16(path, widePath);
    HANDLE handle = CreateFileW(
        widePath.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
        CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL | FILE_FLAG_WRITE_THROUGH,
        nullptr);
    if (handle == INVALID_HANDLE_VALUE)
        throw Poco::OpenFileException(
            "Cannot create process desired-state staging file", path);
    try
    {
        std::size_t offset = 0;
        while (offset < payload.size())
        {
            const auto remaining = payload.size() - offset;
            const DWORD requested = static_cast<DWORD>(std::min<std::size_t>(
                remaining, std::numeric_limits<DWORD>::max()));
            DWORD written = 0;
            if (!WriteFile(handle, payload.data() + offset, requested,
                           &written, nullptr) || written == 0)
                throw Poco::WriteFileException(
                    "Cannot write process desired-state staging file", path);
            offset += static_cast<std::size_t>(written);
        }
        if (!FlushFileBuffers(handle))
            throw Poco::WriteFileException(
                "Cannot flush process desired-state staging file", path);
        if (!CloseHandle(handle))
        {
            handle = INVALID_HANDLE_VALUE;
            throw Poco::WriteFileException(
                "Cannot close process desired-state staging file", path);
        }
        handle = INVALID_HANDLE_VALUE;
    }
    catch (...)
    {
        if (handle != INVALID_HANDLE_VALUE) CloseHandle(handle);
        throw;
    }
#else
    int flags = O_CREAT | O_WRONLY | O_TRUNC;
#if defined(O_CLOEXEC)
    flags |= O_CLOEXEC;
#endif
#if defined(O_NOFOLLOW)
    flags |= O_NOFOLLOW;
#endif
    int descriptor = ::open(path.c_str(), flags, 0660);
    if (descriptor < 0)
        throw Poco::OpenFileException(
            "Cannot create process desired-state staging file", path);
    try
    {
        std::size_t offset = 0;
        while (offset < payload.size())
        {
            const auto written = ::write(
                descriptor, payload.data() + offset,
                payload.size() - offset);
            if (written < 0 && errno == EINTR)
                continue;
            if (written <= 0)
                throw Poco::WriteFileException(
                    "Cannot write process desired-state staging file", path);
            offset += static_cast<std::size_t>(written);
        }
        int synchronized = 0;
        do
        {
            synchronized = ::fsync(descriptor);
        } while (synchronized != 0 && errno == EINTR);
        if (synchronized != 0)
            throw Poco::WriteFileException(
                "Cannot flush process desired-state staging file", path);
        const int closeResult = ::close(descriptor);
        descriptor = -1;
        if (closeResult != 0)
            throw Poco::WriteFileException(
                "Cannot close process desired-state staging file", path);
    }
    catch (...)
    {
        if (descriptor >= 0) ::close(descriptor);
        throw;
    }
#endif
}

#if !defined(POCO_OS_FAMILY_WINDOWS)
void synchronizeParentDirectory(const std::string& path)
{
    Poco::Path parent(path);
    parent.makeParent();
    auto directory = parent.toString();
    if (directory.empty()) directory = ".";
    int flags = O_RDONLY;
#if defined(O_CLOEXEC)
    flags |= O_CLOEXEC;
#endif
#if defined(O_DIRECTORY)
    flags |= O_DIRECTORY;
#endif
    const int descriptor = ::open(directory.c_str(), flags);
    if (descriptor < 0)
        throw Poco::OpenFileException(
            "Cannot open process desired-state parent directory", directory);
    int synchronized = 0;
    do
    {
        synchronized = ::fsync(descriptor);
    } while (synchronized != 0 && errno == EINTR);
    const int closeResult = ::close(descriptor);
    if (synchronized != 0 || closeResult != 0)
        throw Poco::WriteFileException(
            "Cannot synchronize process desired-state parent directory",
            directory);
}
#endif

void replaceFileDurably(const std::string& source,
                        const std::string& destination)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring wideSource;
    std::wstring wideDestination;
    Poco::UnicodeConverter::toUTF16(source, wideSource);
    Poco::UnicodeConverter::toUTF16(destination, wideDestination);
    if (!MoveFileExW(wideSource.c_str(), wideDestination.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
        throw Poco::FileException(
            "Cannot commit process desired-state snapshot", destination);
#else
    if (::rename(source.c_str(), destination.c_str()) != 0)
        throw Poco::FileException(
            "Cannot commit process desired-state snapshot", destination);
    synchronizeParentDirectory(destination);
#endif
}

void removeFileDurably(const std::string& path)
{
#if defined(POCO_OS_FAMILY_WINDOWS)
    std::wstring widePath;
    Poco::UnicodeConverter::toUTF16(path, widePath);
    if (!DeleteFileW(widePath.c_str()))
        throw Poco::FileException(
            "Cannot remove process desired-state snapshot", path);
#else
    if (::unlink(path.c_str()) != 0)
        throw Poco::FileException(
            "Cannot remove process desired-state snapshot", path);
    synchronizeParentDirectory(path);
#endif
}
} // namespace

class ProcessDesiredStateStore::Lease final
{
  public:
    explicit Lease(const std::string& path)
    {
#if defined(POCO_OS_FAMILY_WINDOWS)
        std::wstring widePath;
        Poco::UnicodeConverter::toUTF16(path, widePath);
        _handle = CreateFileW(
            widePath.c_str(), GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ, nullptr, OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL, nullptr);
        if (_handle == INVALID_HANDLE_VALUE)
            throw Poco::FileAccessDeniedException(
                "Process desired-state lease is held by another Runtime",
                path);
#else
        int flags = O_CREAT | O_RDWR;
#if defined(O_CLOEXEC)
        flags |= O_CLOEXEC;
#endif
        _descriptor = ::open(path.c_str(), flags, 0660);
#if !defined(O_CLOEXEC)
        if (_descriptor >= 0 &&
            ::fcntl(_descriptor, F_SETFD, FD_CLOEXEC) != 0)
        {
            ::close(_descriptor);
            _descriptor = -1;
        }
#endif
        if (_descriptor < 0 ||
            ::flock(_descriptor, LOCK_EX | LOCK_NB) != 0)
        {
            if (_descriptor >= 0) ::close(_descriptor);
            _descriptor = -1;
            throw Poco::FileAccessDeniedException(
                "Process desired-state lease is held by another Runtime",
                path);
        }
#endif
        try
        {
            const std::string owner =
                "{\"schemaVersion\":1,\"ownerProcessId\":" +
                std::to_string(Poco::Process::id()) +
                ",\"acquiredAtEpochMicroseconds\":" +
                std::to_string(Poco::Timestamp().epochMicroseconds()) + "}\n";
#if defined(POCO_OS_FAMILY_WINDOWS)
            if (SetFilePointer(_handle, 0, nullptr, FILE_BEGIN) ==
                    INVALID_SET_FILE_POINTER && GetLastError() != NO_ERROR)
                throw Poco::WriteFileException(
                    "Cannot seek process desired-state lease", path);
            if (!SetEndOfFile(_handle))
                throw Poco::WriteFileException(
                    "Cannot truncate process desired-state lease", path);
            DWORD written = 0;
            if (!WriteFile(_handle, owner.data(),
                           static_cast<DWORD>(owner.size()), &written,
                           nullptr) || written != owner.size() ||
                !FlushFileBuffers(_handle))
                throw Poco::WriteFileException(
                    "Cannot record process desired-state lease owner", path);
#else
            if (::ftruncate(_descriptor, 0) != 0 ||
                ::lseek(_descriptor, 0, SEEK_SET) < 0)
                throw Poco::WriteFileException(
                    "Cannot truncate process desired-state lease", path);
            std::size_t offset = 0;
            while (offset < owner.size())
            {
                const auto written = ::write(
                    _descriptor, owner.data() + offset,
                    owner.size() - offset);
                if (written <= 0)
                    throw Poco::WriteFileException(
                        "Cannot record process desired-state lease owner",
                        path);
                offset += static_cast<std::size_t>(written);
            }
            if (::fsync(_descriptor) != 0)
                throw Poco::WriteFileException(
                    "Cannot flush process desired-state lease owner", path);
#endif
        }
        catch (...)
        {
            release();
            throw;
        }
    }

    ~Lease() { release(); }

  private:
    void release() noexcept
    {
#if defined(POCO_OS_FAMILY_WINDOWS)
        if (_handle != INVALID_HANDLE_VALUE)
        {
            CloseHandle(_handle);
            _handle = INVALID_HANDLE_VALUE;
        }
#else
        if (_descriptor >= 0)
        {
            ::flock(_descriptor, LOCK_UN);
            ::close(_descriptor);
            _descriptor = -1;
        }
#endif
    }

#if defined(POCO_OS_FAMILY_WINDOWS)
    HANDLE _handle{INVALID_HANDLE_VALUE};
#else
    int _descriptor{-1};
#endif
};

ProcessDesiredStateStore::ProcessDesiredStateStore(
    std::string path, FaultInjector faultInjector)
    : _path(std::move(path)), _faultInjector(std::move(faultInjector))
{
    if (_path.empty())
        throw Poco::InvalidArgumentException(
            "Process desired-state path must not be empty");
}

ProcessDesiredStateStore::~ProcessDesiredStateStore() = default;

const std::string& ProcessDesiredStateStore::path() const noexcept
{
    return _path;
}

void ProcessDesiredStateStore::acquireLease()
{
    if (_lease)
        return;
    Poco::Path target(_path);
    Poco::Path parent(target);
    parent.makeParent();
    Poco::File(parent).createDirectories();
    _lease = std::make_unique<Lease>(_path + ".lock");
}

bool ProcessDesiredStateStore::leaseHeld() const noexcept
{
    return static_cast<bool>(_lease);
}

void ProcessDesiredStateStore::notifyCommitStage(
    ProcessDesiredStateCommitStage stage) const
{
    if (_faultInjector) _faultInjector(stage);
}

ProcessDesiredStateSnapshot ProcessDesiredStateStore::load() const
{
    if (!_lease)
        throw Poco::IllegalStateException(
            "Process desired-state load requires the single-writer lease");
    const std::vector<std::string> candidates = {
        _path, previousPath(_path)};
    std::string errors;
    bool found = false;
    for (std::size_t index = 0; index < candidates.size(); ++index)
    {
        Poco::File candidate(candidates[index]);
        if (!candidate.exists())
            continue;
        found = true;
        try
        {
            auto snapshot = parseSnapshot(candidates[index]);
            if (index != 0)
            {
                snapshot.recovered = true;
                snapshot.recoveredFrom = candidates[index];
            }
            return snapshot;
        }
        catch (const Poco::Exception& exception)
        {
            if (!errors.empty()) errors += "; ";
            errors += exception.displayText();
        }
        catch (const std::exception& exception)
        {
            if (!errors.empty()) errors += "; ";
            errors += exception.what();
        }
    }
    if (found)
        throw Poco::DataFormatException(
            "No valid process desired-state recovery snapshot: " + errors,
            _path);
    return {};
}

ProcessDesiredStateIntegrity ProcessDesiredStateStore::inspect(
    std::uint64_t expectedGeneration,
    const std::map<std::string, bool>& expectedStates) const
{
    if (!_lease)
        throw Poco::IllegalStateException(
            "Process desired-state inspection requires the single-writer lease");

    ProcessDesiredStateIntegrity result;
    try
    {
        const auto primary = parseSnapshot(_path);
        if (primary.generation != expectedGeneration ||
            primary.states != expectedStates)
            throw Poco::DataFormatException(
                "Process desired-state primary does not match the active authorization",
                _path);
        result.primaryValid = true;
    }
    catch (const Poco::Exception& exception)
    {
        result.primaryError = exception.displayText();
    }
    catch (const std::exception& exception)
    {
        result.primaryError = exception.what();
    }

    const auto backupPath = previousPath(_path);
    result.previousAvailable = Poco::File(backupPath).exists();
    if (result.previousAvailable)
    {
        try
        {
            const auto previous = parseSnapshot(backupPath);
            if (previous.generation >= expectedGeneration)
                throw Poco::DataFormatException(
                    "Process desired-state previous generation is not older than the primary",
                    backupPath);
            result.previousValid = true;
        }
        catch (const Poco::Exception& exception)
        {
            result.previousError = exception.displayText();
        }
        catch (const std::exception& exception)
        {
            result.previousError = exception.what();
        }
    }
    return result;
}

void ProcessDesiredStateStore::save(
    std::uint64_t generation,
    const std::map<std::string, bool>& states) const
{
    if (!_lease)
        throw Poco::IllegalStateException(
            "Process desired-state save requires the single-writer lease");
    Poco::Path target(_path);
    Poco::Path parent(target);
    parent.makeParent();
    Poco::File(parent).createDirectories();

    const auto stagingPath = temporaryPath(_path);
    const auto backupPath = previousPath(_path);
    Poco::File staging(stagingPath);
    requireRegularFile(staging, "staging file");
    if (staging.exists()) removeFileDurably(stagingPath);

    const auto payload = serialize(generation, states);
    writeFileDurably(stagingPath, payload);
    const auto verified = parseSnapshot(stagingPath);
    if (verified.generation != generation || verified.states != states)
        throw Poco::DataFormatException(
            "Process desired-state staging verification changed content",
            stagingPath);
    notifyCommitStage(ProcessDesiredStateCommitStage::stagingFlushed);

    Poco::File current(_path);
    Poco::File backup(backupPath);
    requireRegularFile(current, "current snapshot");
    requireRegularFile(backup, "recovery snapshot");
    const bool currentValid = current.exists() && validSnapshot(_path);
    if (current.exists() && !currentValid)
        removeFileDurably(_path);
    if (currentValid)
    {
        replaceFileDurably(_path, backupPath);
        notifyCommitStage(
            ProcessDesiredStateCommitStage::previousCommitted);
    }

    try
    {
        replaceFileDurably(stagingPath, _path);
    }
    catch (...)
    {
        if (!Poco::File(_path).exists() && Poco::File(backupPath).exists())
            replaceFileDurably(backupPath, _path);
        throw;
    }
    notifyCommitStage(ProcessDesiredStateCommitStage::primaryCommitted);
}
} // namespace PocoDDS::ProcessManagement::Detail
