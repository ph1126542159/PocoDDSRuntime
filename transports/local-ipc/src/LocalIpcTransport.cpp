#include "PocoDDS/LocalIpc/LocalIpcTransport.h"
#include "PocoDDS/RuntimeCore/Codec.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstring>
#include <limits>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#else
#include <cerrno>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>
#endif

namespace PocoDDS::LocalIpc
{
using namespace PocoDDS::RuntimeCore;
namespace
{
#ifdef _WIN32
using NativeHandle = HANDLE;
const NativeHandle invalidHandle = INVALID_HANDLE_VALUE;
#else
using NativeHandle = int;
constexpr NativeHandle invalidHandle = -1;
#endif

RuntimeError ipcError(RuntimeErrorCode code, std::string message, bool retryable = false)
{
    return {code, std::move(message), retryable};
}

std::string platformMessage(const std::string& operation)
{
#ifdef _WIN32
    return operation + " failed with Windows error " + std::to_string(GetLastError());
#else
    return operation + " failed: " + std::string(std::strerror(errno));
#endif
}

void closeNative(NativeHandle handle) noexcept
{
    if (handle == invalidHandle)
        return;
#ifdef _WIN32
    CancelIoEx(handle, nullptr);
    CloseHandle(handle);
#else
    ::shutdown(handle, SHUT_RDWR);
    ::close(handle);
#endif
}

bool readExact(NativeHandle handle, std::uint8_t* destination, std::size_t size)
{
    while (size != 0)
    {
#ifdef _WIN32
        DWORD read = 0;
        const auto chunk = static_cast<DWORD>(std::min<std::size_t>(size, MAXDWORD));
        OVERLAPPED operation{};
        operation.hEvent = CreateEventA(nullptr, TRUE, FALSE, nullptr);
        if (!operation.hEvent)
            return false;
        bool succeeded = ReadFile(handle, destination, chunk, nullptr, &operation) != FALSE;
        if (!succeeded && GetLastError() == ERROR_IO_PENDING)
        {
            succeeded = WaitForSingleObject(operation.hEvent, INFINITE) == WAIT_OBJECT_0 &&
                        GetOverlappedResult(handle, &operation, &read, FALSE) != FALSE;
        }
        else if (succeeded)
        {
            succeeded = GetOverlappedResult(handle, &operation, &read, TRUE) != FALSE;
        }
        CloseHandle(operation.hEvent);
        if (!succeeded || read == 0)
            return false;
#else
        const auto read = ::recv(handle, destination, size, 0);
        if (read == 0)
            return false;
        if (read < 0)
        {
            if (errno == EINTR)
                continue;
            return false;
        }
#endif
        destination += read;
        size -= read;
    }
    return true;
}

bool writeExact(NativeHandle handle, const std::uint8_t* source, std::size_t size)
{
    while (size != 0)
    {
#ifdef _WIN32
        DWORD written = 0;
        const auto chunk = static_cast<DWORD>(std::min<std::size_t>(size, MAXDWORD));
        OVERLAPPED operation{};
        operation.hEvent = CreateEventA(nullptr, TRUE, FALSE, nullptr);
        if (!operation.hEvent)
            return false;
        bool succeeded = WriteFile(handle, source, chunk, nullptr, &operation) != FALSE;
        if (!succeeded && GetLastError() == ERROR_IO_PENDING)
        {
            succeeded = WaitForSingleObject(operation.hEvent, INFINITE) == WAIT_OBJECT_0 &&
                        GetOverlappedResult(handle, &operation, &written, FALSE) != FALSE;
        }
        else if (succeeded)
        {
            succeeded = GetOverlappedResult(handle, &operation, &written, TRUE) != FALSE;
        }
        CloseHandle(operation.hEvent);
        if (!succeeded || written == 0)
            return false;
#else
        const auto written = ::send(handle, source, size, MSG_NOSIGNAL);
        if (written < 0)
        {
            if (errno == EINTR)
                continue;
            return false;
        }
        if (written == 0)
            return false;
#endif
        source += written;
        size -= written;
    }
    return true;
}

void appendU32(std::vector<std::uint8_t>& output, std::uint32_t value)
{
    for (unsigned shift = 0; shift < 32; shift += 8)
        output.push_back(static_cast<std::uint8_t>((value >> shift) & 0xffU));
}

struct Envelope
{
    std::string token;
    TopicSpec topic;
    Message message;
};

Outcome<std::vector<std::uint8_t>> encode(const std::string& token, const TopicSpec& topic,
                                          const Message& message, std::size_t maximumFrameBytes)
{
    if (token.size() > 4096 || token.size() > std::numeric_limits<std::uint32_t>::max())
        return Outcome<std::vector<std::uint8_t>>::failure(
            ipcError(RuntimeErrorCode::invalidArgument,
                     "local IPC authentication token exceeds 4096 bytes"));
    MessageCodecLimits limits;
    limits.maximumFrameBytes = maximumFrameBytes;
    const auto encodedMessage = encodeMessageFrame(topic, message, limits);
    if (!encodedMessage)
        return Outcome<std::vector<std::uint8_t>>::failure(encodedMessage.error());
    std::vector<std::uint8_t> output{'P', 'D', 'R', 'I', 2};
    appendU32(output, static_cast<std::uint32_t>(token.size()));
    output.insert(output.end(), token.begin(), token.end());
    output.insert(output.end(), encodedMessage.value().begin(), encodedMessage.value().end());
    if (output.size() > maximumFrameBytes)
        return Outcome<std::vector<std::uint8_t>>::failure(ipcError(
            RuntimeErrorCode::invalidArgument, "local IPC frame exceeds configured limit"));
    return Outcome<std::vector<std::uint8_t>>::success(std::move(output));
}

Outcome<Envelope> decode(const std::vector<std::uint8_t>& input, std::size_t maximumFrameBytes)
{
    if (input.size() < 9 || input[0] != 'P' || input[1] != 'D' || input[2] != 'R' ||
        input[3] != 'I' || input[4] != 2)
        return Outcome<Envelope>::failure(ipcError(
            RuntimeErrorCode::protocolError, "unsupported local IPC frame signature or version"));
    const auto tokenSize =
        static_cast<std::uint32_t>(input[5]) | (static_cast<std::uint32_t>(input[6]) << 8) |
        (static_cast<std::uint32_t>(input[7]) << 16) | (static_cast<std::uint32_t>(input[8]) << 24);
    if (tokenSize > 4096 || tokenSize > input.size() - 9)
        return Outcome<Envelope>::failure(
            ipcError(RuntimeErrorCode::protocolError, "local IPC token length is invalid"));
    Envelope envelope;
    envelope.token.assign(reinterpret_cast<const char*>(input.data() + 9), tokenSize);
    std::vector<std::uint8_t> encodedMessage(
        input.begin() + static_cast<std::ptrdiff_t>(9 + tokenSize), input.end());
    MessageCodecLimits limits;
    limits.maximumFrameBytes = maximumFrameBytes;
    const auto decodedMessage = decodeMessageFrame(encodedMessage, limits);
    if (!decodedMessage)
        return Outcome<Envelope>::failure(decodedMessage.error());
    envelope.topic = decodedMessage.value().topic;
    envelope.message = decodedMessage.value().message;
    return Outcome<Envelope>::success(std::move(envelope));
}

std::array<std::uint8_t, 4> frameHeader(std::size_t size)
{
    if (size > std::numeric_limits<std::uint32_t>::max())
        throw std::length_error("IPC frame exceeds protocol limit");
    const auto value = static_cast<std::uint32_t>(size);
    return {static_cast<std::uint8_t>(value), static_cast<std::uint8_t>(value >> 8),
            static_cast<std::uint8_t>(value >> 16), static_cast<std::uint8_t>(value >> 24)};
}

std::uint32_t frameSize(const std::array<std::uint8_t, 4>& header)
{
    return static_cast<std::uint32_t>(header[0]) | (static_cast<std::uint32_t>(header[1]) << 8) |
           (static_cast<std::uint32_t>(header[2]) << 16) |
           (static_cast<std::uint32_t>(header[3]) << 24);
}

#ifdef _WIN32
std::string pipeName(const std::string& endpoint)
{
    const std::string prefix = "\\\\.\\pipe\\";
    return endpoint.rfind(prefix, 0) == 0 ? endpoint : prefix + endpoint;
}
#endif
} // namespace

struct LocalIpcTransport::State : public std::enable_shared_from_this<State>
{
    struct Peer
    {
        explicit Peer(NativeHandle value) : handle(value) {}
        NativeHandle handle{invalidHandle};
        std::atomic<bool> alive{true};
        std::mutex writeMutex;
        std::thread reader;
    };

    explicit State(LocalIpcOptions value) : options(std::move(value)) {}

    LocalIpcOptions options;
    InProcessTransport local;
    std::atomic<bool> active{false};
    mutable std::mutex peersMutex;
    std::vector<std::shared_ptr<Peer>> peers;
    std::thread acceptThread;
#ifdef _WIN32
    NativeHandle pendingServer{invalidHandle};
#else
    NativeHandle listener{invalidHandle};
#endif

    bool writeFrame(const std::shared_ptr<Peer>& peer, const std::vector<std::uint8_t>& body)
    {
        if (!peer->alive || body.size() > options.maximumFrameBytes)
            return false;
        const auto header = frameHeader(body.size());
        std::lock_guard<std::mutex> lock(peer->writeMutex);
        if (!peer->alive || !writeExact(peer->handle, header.data(), header.size()) ||
            !writeExact(peer->handle, body.data(), body.size()))
        {
            peer->alive = false;
            return false;
        }
        return true;
    }

    void distribute(const std::vector<std::uint8_t>& body, const Peer* source)
    {
        std::vector<std::shared_ptr<Peer>> current;
        {
            std::lock_guard<std::mutex> lock(peersMutex);
            current = peers;
        }
        for (const auto& peer : current)
        {
            if (peer.get() != source && peer->alive)
                writeFrame(peer, body);
        }
    }

    void readLoop(const std::shared_ptr<Peer>& peer)
    {
        while (active && peer->alive)
        {
            std::array<std::uint8_t, 4> header{};
            if (!readExact(peer->handle, header.data(), header.size()))
                break;
            const auto size = frameSize(header);
            if (size == 0 || size > options.maximumFrameBytes)
                break;
            std::vector<std::uint8_t> body(size);
            if (!readExact(peer->handle, body.data(), body.size()))
                break;
            const auto envelope = decode(body, options.maximumFrameBytes);
            if (!envelope || envelope.value().token != options.authenticationToken)
                break;
            local.publish(envelope.value().topic, envelope.value().message);
            if (options.role == EndpointRole::server)
                distribute(body, peer.get());
        }
        peer->alive = false;
    }

    void addPeer(NativeHandle handle)
    {
        auto peer = std::make_shared<Peer>(handle);
        {
            std::lock_guard<std::mutex> lock(peersMutex);
            peers.push_back(peer);
        }
        const auto state = shared_from_this();
        peer->reader = std::thread([state, peer] { state->readLoop(peer); });
    }

#ifdef _WIN32
    NativeHandle createPipe(bool first)
    {
        const auto name = pipeName(options.endpoint);
        return CreateNamedPipeA(
            name.c_str(),
            PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | (first ? FILE_FLAG_FIRST_PIPE_INSTANCE : 0),
            PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
            PIPE_UNLIMITED_INSTANCES, 65536, 65536, 0, nullptr);
    }

    void acceptLoop()
    {
        auto pipe = pendingServer;
        pendingServer = invalidHandle;
        while (active)
        {
            OVERLAPPED operation{};
            operation.hEvent = CreateEventA(nullptr, TRUE, FALSE, nullptr);
            BOOL connected = FALSE;
            if (operation.hEvent)
            {
                connected = ConnectNamedPipe(pipe, &operation);
                if (!connected)
                {
                    const auto error = GetLastError();
                    if (error == ERROR_PIPE_CONNECTED)
                        connected = TRUE;
                    else if (error == ERROR_IO_PENDING &&
                             WaitForSingleObject(operation.hEvent, INFINITE) == WAIT_OBJECT_0)
                    {
                        DWORD transferred = 0;
                        connected = GetOverlappedResult(pipe, &operation, &transferred, FALSE);
                    }
                }
                CloseHandle(operation.hEvent);
            }
            if (!active)
            {
                closeNative(pipe);
                break;
            }
            if (connected)
                addPeer(pipe);
            else
                closeNative(pipe);
            pipe = createPipe(false);
            if (pipe == invalidHandle)
                break;
        }
    }
#else
    void acceptLoop()
    {
        while (active)
        {
            const auto client = ::accept(listener, nullptr, nullptr);
            if (client < 0)
            {
                if (errno == EINTR)
                    continue;
                break;
            }
            if (!active)
            {
                closeNative(client);
                break;
            }
            addPeer(client);
        }
    }
#endif
};

LocalIpcTransport::LocalIpcTransport(LocalIpcOptions options)
    : _state(std::make_shared<State>(std::move(options)))
{
    if (_state->options.endpoint.empty())
        throw std::invalid_argument("local IPC endpoint cannot be empty");
    if (_state->options.maximumFrameBytes < 1024)
        throw std::invalid_argument("local IPC maximumFrameBytes must be at least 1024");
    if (_state->options.connectTimeout.count() < 0)
        throw std::invalid_argument("local IPC connectTimeout cannot be negative");
    if (_state->options.authenticationToken.size() > 4096)
        throw std::invalid_argument("local IPC authenticationToken exceeds 4096 bytes");
}

LocalIpcTransport::~LocalIpcTransport() { stop(); }

Outcome<void> LocalIpcTransport::start()
{
    bool expected = false;
    if (!_state->active.compare_exchange_strong(expected, true))
        return Outcome<void>::success();

#ifdef _WIN32
    if (_state->options.role == EndpointRole::server)
    {
        _state->pendingServer = _state->createPipe(true);
        if (_state->pendingServer == invalidHandle)
        {
            _state->active = false;
            return Outcome<void>::failure(
                ipcError(RuntimeErrorCode::unavailable, platformMessage("CreateNamedPipe")));
        }
        const auto state = _state;
        _state->acceptThread = std::thread([state] { state->acceptLoop(); });
        return Outcome<void>::success();
    }

    const auto name = pipeName(_state->options.endpoint);
    const auto deadline = std::chrono::steady_clock::now() + _state->options.connectTimeout;
    NativeHandle handle = invalidHandle;
    do
    {
        handle = CreateFileA(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
                             FILE_FLAG_OVERLAPPED, nullptr);
        if (handle != invalidHandle)
            break;
        if (GetLastError() != ERROR_PIPE_BUSY && GetLastError() != ERROR_FILE_NOT_FOUND)
            break;
        WaitNamedPipeA(name.c_str(), 50);
    } while (std::chrono::steady_clock::now() < deadline);
    if (handle == invalidHandle)
    {
        _state->active = false;
        return Outcome<void>::failure(ipcError(RuntimeErrorCode::unavailable,
                                               platformMessage("CreateFile named pipe"), true));
    }
    _state->addPeer(handle);
#else
    sockaddr_un address{};
    if (_state->options.endpoint.size() >= sizeof(address.sun_path))
    {
        _state->active = false;
        return Outcome<void>::failure(
            ipcError(RuntimeErrorCode::invalidArgument, "Unix socket path exceeds platform limit"));
    }
    address.sun_family = AF_UNIX;
    std::memcpy(address.sun_path, _state->options.endpoint.c_str(),
                _state->options.endpoint.size() + 1);
    if (_state->options.role == EndpointRole::server)
    {
        _state->listener = ::socket(AF_UNIX, SOCK_STREAM, 0);
        if (_state->listener < 0)
        {
            _state->active = false;
            return Outcome<void>::failure(
                ipcError(RuntimeErrorCode::unavailable, platformMessage("socket")));
        }
        ::unlink(address.sun_path);
        if (::bind(_state->listener, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0 ||
            ::listen(_state->listener, 16) < 0)
        {
            const auto error = platformMessage("bind/listen Unix socket");
            closeNative(_state->listener);
            _state->listener = invalidHandle;
            _state->active = false;
            return Outcome<void>::failure(ipcError(RuntimeErrorCode::unavailable, error));
        }
        if (::chmod(address.sun_path, S_IRUSR | S_IWUSR) < 0)
        {
            const auto error = platformMessage("chmod Unix socket");
            closeNative(_state->listener);
            _state->listener = invalidHandle;
            ::unlink(address.sun_path);
            _state->active = false;
            return Outcome<void>::failure(ipcError(RuntimeErrorCode::unavailable, error));
        }
        const auto state = _state;
        _state->acceptThread = std::thread([state] { state->acceptLoop(); });
        return Outcome<void>::success();
    }

    NativeHandle handle = invalidHandle;
    const auto deadline = std::chrono::steady_clock::now() + _state->options.connectTimeout;
    do
    {
        handle = ::socket(AF_UNIX, SOCK_STREAM, 0);
        if (handle >= 0 &&
            ::connect(handle, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == 0)
            break;
        closeNative(handle);
        handle = invalidHandle;
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
    } while (std::chrono::steady_clock::now() < deadline);
    if (handle == invalidHandle)
    {
        _state->active = false;
        return Outcome<void>::failure(
            ipcError(RuntimeErrorCode::unavailable, platformMessage("connect Unix socket"), true));
    }
    _state->addPeer(handle);
#endif
    return Outcome<void>::success();
}

void LocalIpcTransport::stop() noexcept
{
    if (!_state->active.exchange(false))
        return;

#ifdef _WIN32
    if (_state->options.role == EndpointRole::server)
    {
        const auto name = pipeName(_state->options.endpoint);
        const auto wake = CreateFileA(name.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                      OPEN_EXISTING, 0, nullptr);
        closeNative(wake);
    }
#else
    closeNative(_state->listener);
    _state->listener = invalidHandle;
#endif
    if (_state->acceptThread.joinable())
        _state->acceptThread.join();

    std::vector<std::shared_ptr<State::Peer>> peers;
    {
        std::lock_guard<std::mutex> lock(_state->peersMutex);
        peers = _state->peers;
    }
    for (const auto& peer : peers)
    {
        peer->alive = false;
        closeNative(peer->handle);
    }
    for (const auto& peer : peers)
    {
        if (peer->reader.joinable())
            peer->reader.join();
    }
    {
        std::lock_guard<std::mutex> lock(_state->peersMutex);
        _state->peers.clear();
    }
#ifndef _WIN32
    if (_state->options.role == EndpointRole::server)
        ::unlink(_state->options.endpoint.c_str());
#endif
}

bool LocalIpcTransport::running() const noexcept { return _state->active; }

std::size_t LocalIpcTransport::peerCount() const noexcept
{
    std::lock_guard<std::mutex> lock(_state->peersMutex);
    return static_cast<std::size_t>(std::count_if(_state->peers.begin(), _state->peers.end(),
                                                  [](const auto& peer)
                                                  { return peer->alive.load(); }));
}

std::string LocalIpcTransport::id() const
{
#ifdef _WIN32
    return "named-pipe";
#else
    return "unix-socket";
#endif
}

TransportCapabilities LocalIpcTransport::capabilities() const noexcept
{
    return {false, true, false, false, false, false};
}

Subscription LocalIpcTransport::subscribe(const TopicSpec& topic, Handler handler)
{
    return _state->local.subscribe(topic, std::move(handler));
}

PublishResult LocalIpcTransport::publish(const TopicSpec& topic, const Message& message)
{
    auto result = _state->local.publish(topic, message);
    if (!_state->active)
    {
        ++result.failed;
        return result;
    }

    const auto encoded = encode(_state->options.authenticationToken, topic, message,
                                _state->options.maximumFrameBytes);
    if (!encoded)
    {
        if (encoded.error().code == RuntimeErrorCode::invalidArgument)
            ++result.dropped;
        else
            ++result.failed;
        return result;
    }
    const auto& body = encoded.value();

    std::vector<std::shared_ptr<State::Peer>> peers;
    {
        std::lock_guard<std::mutex> lock(_state->peersMutex);
        peers = _state->peers;
    }
    for (const auto& peer : peers)
    {
        if (!peer->alive)
            continue;
        if (_state->writeFrame(peer, body))
            ++result.accepted;
        else
            ++result.failed;
    }
    return result;
}

} // namespace PocoDDS::LocalIpc
