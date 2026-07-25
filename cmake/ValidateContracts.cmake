set(required_files
    "${SOURCE_DIR}/contracts/schemas/runtime-config.schema.json"
    "${SOURCE_DIR}/contracts/openapi/runtime.yaml"
    "${SOURCE_DIR}/contracts/asyncapi/runtime.yaml")
foreach(path IN LISTS required_files)
    if(NOT EXISTS "${path}")
        message(FATAL_ERROR "Missing contract file: ${path}")
    endif()
    file(READ "${path}" content)
    if(NOT content MATCHES "version|\\$schema")
        message(FATAL_ERROR "Contract has no version/schema declaration: ${path}")
    endif()
endforeach()

file(READ "${SOURCE_DIR}/config/pdr-runtime.properties" runtime_properties)
foreach(required_key
        "osp.web.server.host"
        "osp.web.server.port"
        "pdr.fastdds.domainId"
        "pdr.subprocess.shutdownTimeoutMilliseconds")
    string(FIND "${runtime_properties}" "${required_key} =" key_position)
    if(key_position EQUAL -1)
        message(FATAL_ERROR "Runtime configuration is missing required key: ${required_key}")
    endif()
endforeach()

file(READ "${SOURCE_DIR}/contracts/openapi/runtime.yaml" openapi)
foreach(required_path "/health/live" "/health/ready" "/health/detail")
    string(FIND "${openapi}" "${required_path}:" path_position)
    if(path_position EQUAL -1)
        message(FATAL_ERROR "OpenAPI is missing required path: ${required_path}")
    endif()
endforeach()
message(STATUS "CONTRACT_FILES_PASS")
