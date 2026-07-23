#include "PocoDDS/DDS/EnvelopeTopicDataType.h"

#include <fastcdr/Cdr.h>
#include <fastcdr/FastBuffer.h>
#include <fastcdr/exceptions/Exception.h>
#include <fastdds/rtps/common/CdrSerialization.hpp>

namespace PocoDDS::FastDDS
{
using eprosima::fastdds::dds::DataRepresentationId_t;
using eprosima::fastdds::rtps::InstanceHandle_t;
using eprosima::fastdds::rtps::SerializedPayload_t;

EnvelopeTopicDataType::EnvelopeTopicDataType()
{
    set_name("PocoDDS::FastDDS::Envelope");
    max_serialized_type_size = 256 * 1024;
    is_compute_key_provided = false;
}

bool EnvelopeTopicDataType::serialize(const void* const data,
                                      SerializedPayload_t& payload,
                                      DataRepresentationId_t representation)
{
    const auto& value = *static_cast<const Envelope*>(data);
    eprosima::fastcdr::FastBuffer buffer(reinterpret_cast<char*>(payload.data), payload.max_size);
    eprosima::fastcdr::Cdr serializer(
        buffer,
        eprosima::fastcdr::Cdr::DEFAULT_ENDIAN,
        representation == DataRepresentationId_t::XCDR_DATA_REPRESENTATION
            ? eprosima::fastcdr::CdrVersion::XCDRv1
            : eprosima::fastcdr::CdrVersion::XCDRv2);
    payload.encapsulation =
        serializer.endianness() == eprosima::fastcdr::Cdr::BIG_ENDIANNESS ? CDR_BE : CDR_LE;
    serializer.set_encoding_flag(
        representation == DataRepresentationId_t::XCDR_DATA_REPRESENTATION
            ? eprosima::fastcdr::EncodingAlgorithmFlag::PLAIN_CDR
            : eprosima::fastcdr::EncodingAlgorithmFlag::DELIMIT_CDR2);
    try
    {
        serializer.serialize_encapsulation();
        serializer << value.sequence << value.timestampMicroseconds << value.kind << value.deviceId
                   << value.operation << value.payload << value.correlationId << value.traceParent
                   << value.traceState << value.businessName << value.businessInstanceId
                   << value.status;
        serializer.set_dds_cdr_options({0, 0});
        payload.length = static_cast<std::uint32_t>(serializer.get_serialized_data_length());
        return true;
    }
    catch (const eprosima::fastcdr::exception::Exception&)
    {
        return false;
    }
}

bool EnvelopeTopicDataType::deserialize(SerializedPayload_t& payload, void* data)
{
    auto& value = *static_cast<Envelope*>(data);
    eprosima::fastcdr::FastBuffer buffer(reinterpret_cast<char*>(payload.data), payload.length);
    eprosima::fastcdr::Cdr deserializer(buffer);
    try
    {
        deserializer.read_encapsulation();
        payload.encapsulation =
            deserializer.endianness() == eprosima::fastcdr::Cdr::BIG_ENDIANNESS ? CDR_BE : CDR_LE;
        deserializer >> value.sequence >> value.timestampMicroseconds >> value.kind >>
            value.deviceId >> value.operation >> value.payload >> value.correlationId >>
            value.traceParent >> value.traceState >> value.businessName >>
            value.businessInstanceId >> value.status;
        return true;
    }
    catch (const eprosima::fastcdr::exception::Exception&)
    {
        return false;
    }
}

std::uint32_t EnvelopeTopicDataType::calculate_serialized_size(
    const void* const data,
    DataRepresentationId_t representation)
{
    static_cast<void>(representation);
    const auto& value = *static_cast<const Envelope*>(data);
    constexpr std::uint32_t scalarAndEncapsulation = 4 + 8 + 8 + 4;
    const auto strings = value.kind.size() + value.deviceId.size() + value.operation.size() +
                         value.payload.size() + value.correlationId.size() +
                         value.traceParent.size() + value.traceState.size() +
                         value.businessName.size() + value.businessInstanceId.size();
    return scalarAndEncapsulation + static_cast<std::uint32_t>(strings) + 9 * 8 + 32;
}

bool EnvelopeTopicDataType::compute_key(SerializedPayload_t& payload,
                                        InstanceHandle_t& handle,
                                        bool forceMd5)
{
    static_cast<void>(payload);
    static_cast<void>(handle);
    static_cast<void>(forceMd5);
    return false;
}

bool EnvelopeTopicDataType::compute_key(const void* const data,
                                        InstanceHandle_t& handle,
                                        bool forceMd5)
{
    static_cast<void>(data);
    static_cast<void>(handle);
    static_cast<void>(forceMd5);
    return false;
}

void* EnvelopeTopicDataType::create_data()
{
    return new Envelope;
}

void EnvelopeTopicDataType::delete_data(void* data)
{
    delete static_cast<Envelope*>(data);
}

void EnvelopeTopicDataType::register_type_object_representation() {}
} // namespace PocoDDS::FastDDS
