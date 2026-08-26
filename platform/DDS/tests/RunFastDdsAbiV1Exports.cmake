foreach(required PDR_FASTDDS_ABI_LIBRARY PDR_DUMPBIN)
    if(NOT DEFINED ${required})
        message(FATAL_ERROR "RunFastDdsAbiV1Exports.cmake requires ${required}")
    endif()
endforeach()

execute_process(
    COMMAND "${PDR_DUMPBIN}" /nologo /exports "${PDR_FASTDDS_ABI_LIBRARY}"
    RESULT_VARIABLE result
    OUTPUT_VARIABLE output
    ERROR_VARIABLE error)
if(NOT result EQUAL 0)
    message(FATAL_ERROR "dumpbin failed (${result}): ${error}\n${output}")
endif()

string(REGEX MATCHALL
    "[\r\n][ \t]*[0-9]+[ \t]+[0-9A-Fa-f]+[ \t]+[0-9A-Fa-f]+[ \t]+[^ \t\r\n]+"
    export_lines "${output}")
set(actual)
foreach(line IN LISTS export_lines)
    string(REGEX REPLACE ".*[ \t]([^ \t\r\n]+)$" "\\1" symbol "${line}")
    list(APPEND actual "${symbol}")
endforeach()
list(REMOVE_DUPLICATES actual)
list(SORT actual)

set(expected
    pdr_fastdds_abi_version_v1
    pdr_fastdds_envelope_size_v1
    pdr_fastdds_runtime_create_v1
    pdr_fastdds_runtime_destroy_v1
    pdr_fastdds_runtime_prepare_publisher_v1
    pdr_fastdds_runtime_publish_v1
    pdr_fastdds_runtime_start_v1
    pdr_fastdds_runtime_started_v1
    pdr_fastdds_runtime_stop_v1
    pdr_fastdds_runtime_subscribe_v1
    pdr_fastdds_subscription_destroy_v1
    pdr_fastdds_subscription_unsubscribe_v1)
list(SORT expected)

if(NOT actual STREQUAL expected)
    message(FATAL_ERROR
        "PDRFastDDSAbiV1 export contract mismatch\nexpected=${expected}\nactual=${actual}")
endif()
message(STATUS "FAST_DDS_ABI_V1_EXPORTS_PASS symbols=12")
