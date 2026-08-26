#include <chrono>
#include <fstream>
#include <string>
#include <thread>

int main(int argc, char** argv)
{
    if (argc != 6)
        return 64;
    const std::string transactionPath = argv[1];
    const std::string countPath = argv[2];
    const std::string transactionId = argv[3];
    const std::string mode = argv[4];
    const std::string candidateDigest = argv[5];

    int launches = 0;
    { std::ifstream input(countPath); input >> launches; }
    { std::ofstream output(countPath, std::ios::trunc); output << ++launches << '\n'; }

    if (launches == 2)
    {
        if (mode == "rollback")
            return 17;
        std::ofstream output(transactionPath, std::ios::trunc);
        output << "transactionId=" << transactionId
               << "\nstate=activationReady\nbundleCount=1\ncandidateDigest="
               << candidateDigest << "\nerror=\n";
    }

    // Stay alive long enough for readiness/probation checks, but keep the
    // fixture independent of platform-specific graceful termination behavior.
    std::this_thread::sleep_for(std::chrono::seconds(3));
    return 0;
}
