using OpenJPH
using Test

@testset "OpenJPH" begin

    @testset "Round-trip: $T" for T in (UInt8, Int8, UInt16, Int16, UInt32, Int32)
        data = T == UInt8  ? rand(T, 64, 128) :
               T == Int8   ? rand(T, 64, 128) :
               T == UInt16 ? rand(T, 64, 128) :
               T == Int16  ? rand(T, 64, 128) :
               T == UInt32 ? rand(UInt32(0):UInt32(10000), 64, 128) :
                             rand(Int32(-5000):Int32(5000), 64, 128)
        enc = openjph_encode(data)
        @test enc isa Vector{UInt8}
        @test length(enc) > 0
        dec = openjph_decode(enc)
        @test dec isa Array{T}
        @test dec == data
    end

    @testset "Round-trip: 3D UInt16" begin
        data = rand(UInt16, 3, 32, 64)
        enc  = openjph_encode(data)
        dec  = openjph_decode(enc)
        @test dec isa Array{UInt16}
        @test dec == data
    end

    @testset "Round-trip: 3D UInt16 color_transform" begin
        data = rand(UInt16, 3, 32, 64)
        enc  = openjph_encode(data; color_transform=true)
        dec  = openjph_decode(enc; color_transform=true)
        @test dec isa Array{UInt16}
        @test dec == data
    end

    @testset "Irreversible (lossy): UInt16" begin
        data = rand(UInt16, 64, 128)
        enc  = openjph_encode(data; irreversible=true)
        dec  = openjph_decode(enc)
        @test dec isa Array{UInt16}
        @test size(dec) == size(data)
        @test maximum(abs.(Int32.(dec) .- Int32.(data))) < div(typemax(UInt16), 4)
    end

    @testset "Output is independent of input buffer" begin
        data = rand(UInt16, 64, 64)
        enc  = openjph_encode(data)
        fill!(data, 0)
        dec = openjph_decode(enc)
        @test any(dec .!= 0)
    end

end
